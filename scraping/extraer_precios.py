"""Extracción diaria de precios, descuentos y stock antes del Buen Fin 2026.

Recorre las categorías de laptops y tablets de Cyberpuerta y Elektra y guarda
una observación por producto x tienda x ejecución. Cada registro conserva la
URL de origen y la fecha de extracción. Pensado para ejecutarse una vez al día.

Uso:
    python scraping/extraer_precios.py                       # todo, 300 por categoría
    python scraping/extraer_precios.py --tiendas elektra --categorias tablets --max 50 --visible
"""

import argparse
import csv
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

RAIZ = Path(__file__).resolve().parent.parent
DIR_SALIDA = RAIZ / "data" / "raw"
REGISTRO_EJECUCIONES = DIR_SALIDA / "registro_ejecuciones.csv"

CATEGORIAS = {
    "cyberpuerta": {
        "laptops": "https://www.cyberpuerta.mx/Computadoras/Laptops/",
        "tablets": "https://www.cyberpuerta.mx/Computadoras/Tablets/Tablets/",
    },
    # En Elektra estas rutas son resultados de búsqueda: incluyen accesorios,
    # que se filtran en la limpieza con la columna categoria_tienda.
    "elektra": {
        "laptops": "https://www.elektra.mx/laptops",
        "tablets": "https://www.elektra.mx/tablets",
    },
}

PAUSA_MIN, PAUSA_MAX = 3.0, 6.0  # segundos entre páginas, para no saturar al sitio

CAMPOS = [
    "tienda", "categoria", "fecha_extraccion", "url_origen", "url_producto", "posicion",
    "id_producto", "modelo", "nombre", "marca", "vendedor", "categoria_tienda",
    "precio_actual", "precio_lista", "descuento_anunciado_pct",
    "costo_envio", "stock_piezas", "stock_texto", "disponibilidad", "especificaciones",
]

# Textos que indican un reto antibots o CAPTCHA. Si aparecen, la tienda se omite:
# el proyecto no evade protecciones.
SENALES_BLOQUEO = ("just a moment", "un momento", "captcha", "verifica tu identidad",
                   "access denied", "acceso denegado", "verifying you are human")


class BloqueoDetectado(Exception):
    pass


def ahora_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def pausa():
    time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))


def a_numero(texto):
    """'$21,609.00' -> 21609.0 ; None si no hay número."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(texto))
    return float(m.group().replace(",", "")) if m else None


def piezas(texto):
    """'140 pzas.' -> 140 ; 'Solo 1 pza.' -> 1."""
    m = re.search(r"(\d[\d,]*)\s*pza", texto or "")
    return int(m.group(1).replace(",", "")) if m else None


def crear_driver(visible=False):
    opciones = webdriver.ChromeOptions()
    if not visible:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--window-size=1366,900")
    opciones.add_argument("--lang=es-MX")
    driver = webdriver.Chrome(options=opciones)  # Selenium Manager resuelve el chromedriver
    driver.set_page_load_timeout(60)
    return driver


def revisar_bloqueo(driver):
    texto = (driver.title + " " + driver.find_element(By.TAG_NAME, "body").text[:500]).lower()
    if any(s in texto for s in SENALES_BLOQUEO):
        raise BloqueoDetectado(f"{driver.current_url} -> '{driver.title}'")


# ---------------------------------------------------------------- Cyberpuerta

JS_CYBERPUERTA = r"""
const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
  .map(s => { try { return JSON.parse(s.textContent); } catch (e) { return null; } })
  .filter(Boolean)
  .flatMap(d => d['@graph'] || [d])
  .filter(g => g['@type'] === 'ItemList')
  .flatMap(g => g.itemListElement.map(e => e.item));
const porUrl = Object.fromEntries(ld.map(p => [p.url, p]));

return [...document.querySelectorAll('.cpd-product-card-catalog-list')].map(c => {
  const q = s => c.querySelector(s);
  const url = q('a[href$=".html"]')?.href || null;
  // El precio se dibuja con un componente animado (number-flow); su texto accesible
  // está en ElementInternals, no en el DOM visible.
  const nf = q('.cp-text--price-total number-flow-vue');
  const hojas = [...c.querySelectorAll('*')].filter(e => e.childElementCount === 0);
  // La imagen del producto se llama CP-<MARCA>-<SKU>-xxxx.png
  const img = [...c.querySelectorAll('img')].map(i => i.getAttribute('src') || '')
    .find(s => s.includes('/img/product/')) || '';
  const specs = {};
  c.querySelectorAll('.key-text').forEach(k => {
    const v = k.parentElement.querySelector('.value-text');
    specs[k.textContent.trim().replace(/:$/, '')] = v ? v.textContent.trim() : null;
  });
  const p = porUrl[url] || {};
  return {
    url_producto: url,
    nombre: q('.cpd-product-card-catalog-list__product-name')?.innerText.trim() || p.name || null,
    modelo: q('.cpd-product-card-catalog-list__description-container .cp-text--caption-regular.cp-text--block')
              ?.textContent.trim() || p.sku || null,
    marca: p.brand?.name || img.match(/\/CP-([^-/]+)-/)?.[1] || null,
    gtin: p.gtin13 || null,
    categoria: p.category || null,
    precio_dom: nf?._internals?.ariaLabel || null,
    precio_ld: p.offers?.price ?? null,
    precio_lista: q('.cp-price-odometer__offer')?.textContent.trim() || null,
    descuento: hojas.map(e => e.textContent.trim()).find(t => /^-\d+%$/.test(t)) || null,
    envio: q('.cpd-stock-shipping-module__shipping-info-container')?.innerText || null,
    stock_texto: q('.cpd-stock-shipping-module__available-container')?.innerText.trim() || null,
    disponibilidad: p.offers?.availability || null,
    specs: specs,
  };
});
"""


def cargar_tarjetas_cyberpuerta(driver, espera=20):
    """Las tarjetas a partir de la ~17 se cargan al desplazarse (lazy loading)."""
    limite = time.time() + espera
    pendientes = None
    while time.time() < limite:
        driver.execute_script("""
            for (const s of document.querySelectorAll('.cpd-catalog-product-card-slot'))
              if (s.querySelector('.skeleton-block')) { s.scrollIntoView({block: 'center'}); break; }
        """)
        time.sleep(0.8)
        pendientes = driver.execute_script(
            "return document.querySelectorAll('.cpd-catalog-product-card-slot .skeleton-block').length")
        if pendientes == 0:
            return 0
    return pendientes


def extraer_cyberpuerta(driver, url_base, categoria, maximo):
    registros, pagina = [], 1
    while len(registros) < maximo:
        url = url_base if pagina == 1 else f"{url_base}?pgNr={pagina}"
        driver.get(url)
        revisar_bloqueo(driver)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".cpd-product-card-catalog-list")))
        except TimeoutException:
            print(f"  sin productos en {url}; fin de la categoría")
            break
        sin_cargar = cargar_tarjetas_cyberpuerta(driver)
        if sin_cargar:
            print(f"  aviso: {sin_cargar} tarjetas no cargaron en {url}")
        fecha = ahora_iso()
        tarjetas = driver.execute_script(JS_CYBERPUERTA)
        for i, t in enumerate(tarjetas, start=1):
            envio = t["envio"] or ""
            registros.append({
                "tienda": "cyberpuerta",
                "categoria": categoria,
                "fecha_extraccion": fecha,
                "url_origen": url,
                "url_producto": t["url_producto"],
                "posicion": len(registros) + 1,
                "id_producto": t["gtin"],
                "modelo": t["modelo"],
                "nombre": t["nombre"],
                "marca": t["marca"],
                "vendedor": "Cyberpuerta",
                "categoria_tienda": t["categoria"],
                "precio_actual": a_numero(t["precio_dom"]) or a_numero(t["precio_ld"]),
                "precio_lista": a_numero(t["precio_lista"]),
                "descuento_anunciado_pct": a_numero(t["descuento"]),
                "costo_envio": 0.0 if "gratis" in envio.lower() else a_numero(envio),
                "stock_piezas": piezas(t["stock_texto"]),
                "stock_texto": t["stock_texto"],
                "disponibilidad": (t["disponibilidad"] or "").rsplit("/", 1)[-1] or None,
                "especificaciones": json.dumps(t["specs"], ensure_ascii=False) if t["specs"] else None,
            })
        print(f"  página {pagina}: {len(registros)} productos")
        if len(tarjetas) < 24:  # última página
            break
        pagina += 1
        pausa()
    return registros[:maximo]


# -------------------------------------------------------------------- Elektra

JS_ELEKTRA = r"""
return [...document.querySelectorAll('cite[data-all]')].map(c => {
  const a = c.closest('a[href]');
  const hojas = a ? [...a.querySelectorAll('*')].filter(e => e.childElementCount === 0) : [];
  return {
    datos: c.dataset.all,
    url_producto: a?.href || null,
    descuento: hojas.map(e => e.textContent.trim()).find(t => /^-\d+%$/.test(t)) || null,
    agotado: a ? /agotado/i.test(a.innerText) : null,
  };
});
"""


def boton_mostrar_mas(driver):
    for b in driver.find_elements(By.CSS_SELECTOR, "button"):
        if "MOSTRAR M" in b.text.upper():
            return b
    return None


def extraer_elektra(driver, url, categoria, maximo):
    driver.get(url)
    revisar_bloqueo(driver)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "cite[data-all]")))
    # "MOSTRAR MÁS" agrega productos a la misma página: hay que pulsarlo con Selenium.
    while True:
        n = len(driver.find_elements(By.CSS_SELECTOR, "cite[data-all]"))
        print(f"  {n} productos cargados")
        boton = boton_mostrar_mas(driver)
        if n >= maximo or boton is None:
            break
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", boton)
        try:
            WebDriverWait(driver, 20).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, "cite[data-all]")) > n)
        except TimeoutException:
            print("  'MOSTRAR MÁS' no agregó productos; se detiene")
            break
        revisar_bloqueo(driver)
        pausa()

    fecha = ahora_iso()
    registros = []
    for i, t in enumerate(driver.execute_script(JS_ELEKTRA)[:maximo], start=1):
        d = json.loads(t["datos"])
        registros.append({
            "tienda": "elektra",
            "categoria": categoria,
            "fecha_extraccion": fecha,
            "url_origen": url,
            "url_producto": t["url_producto"],
            "posicion": i,
            "id_producto": d.get("product_id"),
            "modelo": d.get("modelo"),
            "nombre": d.get("item_name"),
            "marca": d.get("item_brand"),
            # sellerId "1" es Elektra; los demás son vendedores del marketplace
            "vendedor": "Elektra" if d.get("sellerId") == "1" else (d.get("vendor") or d.get("sellerId")),
            "categoria_tienda": d.get("item_category3"),
            "precio_actual": a_numero(d.get("price")),
            "precio_lista": a_numero(d.get("price_without_discount")),
            "descuento_anunciado_pct": a_numero(t["descuento"]),
            "costo_envio": None,   # no se muestra en el listado
            "stock_piezas": None,  # Elektra no publica piezas
            "stock_texto": "agotado" if t["agotado"] else None,
            "disponibilidad": None,
            "especificaciones": None,
        })
    return registros


# ----------------------------------------------------------------- Ejecución

EXTRACTORES = {"cyberpuerta": extraer_cyberpuerta, "elektra": extraer_elektra}


def guardar(registros, tienda, categoria, inicio):
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = DIR_SALIDA / f"{inicio:%Y-%m-%d_%H%M}_{tienda}_{categoria}.csv"
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(registros)
    return ruta


def anotar_ejecucion(tienda, categoria, n, segundos, estado):
    """Bitácora de cada corrida: sirve para documentar fallos y bloqueos en el reporte."""
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    nuevo = not REGISTRO_EJECUCIONES.exists()
    try:
        with open(REGISTRO_EJECUCIONES, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["fecha", "tienda", "categoria", "registros", "segundos", "estado"])
            w.writerow([ahora_iso(), tienda, categoria, n, round(segundos), estado])
    except PermissionError:
        # Pasa si el archivo está abierto en Excel; los datos ya se guardaron.
        print(f"  aviso: no se pudo escribir {REGISTRO_EJECUCIONES.name} (¿abierto en Excel?)")


def resumen(registros, segundos):
    n = len(registros)
    unicos = len({r["url_producto"] for r in registros})
    print(f"  = {n} registros, {unicos} URLs únicas, {segundos:.0f} s")
    vacios = [c for c in CAMPOS if not any(r[c] not in (None, "") for r in registros)]
    if vacios:
        print(f"  campos siempre vacíos: {', '.join(vacios)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tiendas", nargs="+", choices=list(CATEGORIAS), default=list(CATEGORIAS))
    p.add_argument("--categorias", nargs="+", choices=["laptops", "tablets"], default=["laptops", "tablets"])
    p.add_argument("--max", type=int, default=300, help="productos por tienda y categoría (default 300)")
    p.add_argument("--visible", action="store_true", help="mostrar el navegador")
    args = p.parse_args()

    inicio_corrida = datetime.now()
    driver = crear_driver(args.visible)
    try:
        for tienda in args.tiendas:
            for categoria in args.categorias:
                print(f"\n>> {tienda} / {categoria}")
                inicio = time.time()
                try:
                    registros = EXTRACTORES[tienda](driver, CATEGORIAS[tienda][categoria], categoria, args.max)
                except BloqueoDetectado as e:
                    print(f"  BLOQUEO: {e}. Se omite.")
                    anotar_ejecucion(tienda, categoria, 0, time.time() - inicio, f"bloqueo: {e}")
                    continue
                except (TimeoutException, WebDriverException) as e:
                    print(f"  ERROR: {e.__class__.__name__}. Se omite.")
                    anotar_ejecucion(tienda, categoria, 0, time.time() - inicio, f"error: {e.__class__.__name__}")
                    continue
                ruta = guardar(registros, tienda, categoria, inicio_corrida)
                resumen(registros, time.time() - inicio)
                anotar_ejecucion(tienda, categoria, len(registros), time.time() - inicio, "ok")
                print(f"  guardado en {ruta.relative_to(RAIZ)}")
                pausa()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
