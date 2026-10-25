"""Extracción diaria de precios, descuentos y stock antes del Buen Fin 2026.

Fuentes:
- Cyberpuerta: listados de categoría con Selenium (carga diferida de tarjetas y
  precio dibujado con un componente animado). Se recorren páginas hasta reunir
  --max fichas válidas y, si existe un panel, hasta encontrar sus publicaciones.
- Elektra: catálogo público de la tienda (API VTEX permitida en su robots.txt),
  por categoría exacta y en orden fijo. Su listado web cambia de orden en cada
  carga, por lo que no sirve para seguir las mismas publicaciones.

Cada fila es una observación oferta x corrida, con URL de origen, fecha de
extracción, claves (ver comun.py) y si entra al estudio o por qué se excluye.
Los CSV originales nunca se modifican: cada corrida crea archivos nuevos.

Uso:
    python scraping/extraer_precios.py
    python scraping/extraer_precios.py --tiendas cyberpuerta --categorias tablets --max 30 --visible
"""

import argparse
import csv
import hashlib
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import comun

RAIZ = Path(__file__).resolve().parent.parent
DIR_SALIDA = RAIZ / "data" / "raw"
REGISTRO_CORRIDAS = DIR_SALIDA / "registro_corridas.csv"
PANEL = RAIZ / "data" / "procesado" / "panel.csv"

URL_CYBERPUERTA = {
    "laptops": "https://www.cyberpuerta.mx/Computadoras/Laptops/",
    "tablets": "https://www.cyberpuerta.mx/Computadoras/Tablets/Tablets/",
}
# Rutas de categoría del catálogo de Elektra (Cómputo > Portátiles > ..., Cómputo > Tablets y Accesorios > Tablets)
CATEGORIAS_ELEKTRA = {
    "laptops": ["1371654/1371720/1372099", "1371654/1371720/4656482", "1371654/1371720/1372102"],
    "tablets": ["1371654/1371728/1372132"],
}
API_ELEKTRA = "https://www.elektra.mx/api/catalog_system/pub/products/search"
LOTE_API = 50  # máximo que acepta la API por petición

PAUSA_MIN, PAUSA_MAX = 3.0, 6.0  # segundos entre páginas web
PAUSA_API = 1.5                  # segundos entre peticiones a la API
AGENTE_API = "Mozilla/5.0 (compatible; proyecto-academico-precios/1.0)"

CAMPOS = [
    "corrida_id", "fecha_corrida", "tienda", "categoria", "fuente", "cobertura",
    "fecha_extraccion", "url_origen", "url_producto", "posicion",
    "id_producto", "sku_id", "sku_orden", "gtin", "modelo", "nombre", "marca",
    "vendedor", "vendedor_id", "vendedor_predeterminado", "categoria_tienda",
    "condicion", "es_paquete",
    "precio_actual", "precio_lista", "descuento_anunciado_pct",
    "costo_envio", "stock_piezas", "stock_texto", "disponible", "disponibilidad",
    "especificaciones",
    "clave_publicacion", "clave_oferta", "clave_producto_candidata",
    "incluido", "motivo_exclusion",
]

# Textos que indican un reto antibots o CAPTCHA. Si aparecen, la tienda se omite:
# el proyecto no evade protecciones.
SENALES_BLOQUEO = ("just a moment", "un momento", "captcha", "verifica tu identidad",
                   "access denied", "acceso denegado", "verifying you are human")


class BloqueoDetectado(Exception):
    pass


def ahora_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def pausa(minimo=PAUSA_MIN, maximo=PAUSA_MAX):
    time.sleep(random.uniform(minimo, maximo))


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


def completar(fila, corrida, vistos):
    """Agrega claves, condición y la decisión de inclusión. `vistos` evita duplicados en la corrida."""
    fila.update(corrida)
    fila["clave_publicacion"] = comun.clave_publicacion(fila["tienda"], fila["url_producto"], fila["id_producto"])
    fila["clave_oferta"] = comun.clave_oferta(fila["clave_publicacion"], fila["vendedor"], fila["sku_id"])
    fila["clave_producto_candidata"] = comun.clave_producto_candidata(fila["marca"], fila["modelo"])
    fila["condicion"] = comun.condicion(fila["nombre"], fila["categoria_tienda"])
    fila["es_paquete"] = comun.es_paquete(fila["nombre"])
    motivo = comun.motivo_exclusion(fila["categoria"], fila["nombre"], fila["categoria_tienda"], fila["tienda"],
                                    fila["precio_actual"], fila["disponible"], fila["vendedor"])
    if motivo is None and fila["clave_oferta"] in vistos:
        motivo = "duplicado_en_corrida"
    vistos.add(fila["clave_oferta"])
    fila["incluido"] = motivo is None
    fila["motivo_exclusion"] = motivo
    return fila


def leer_panel(tienda, categoria):
    if not PANEL.exists():
        return set()
    with open(PANEL, encoding="utf-8-sig") as f:
        return {r["clave_publicacion"] for r in csv.DictReader(f)
                if r["tienda"] == tienda and r["categoria"] == categoria}


# ---------------------------------------------------------------- Cyberpuerta

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


def extraer_cyberpuerta(driver, categoria, maximo, corrida, max_paginas):
    url_base = URL_CYBERPUERTA[categoria]
    panel = leer_panel("cyberpuerta", categoria)
    registros, vistos, pagina = [], set(), 1
    while pagina <= max_paginas:
        validos = sum(r["incluido"] for r in registros)
        faltan_panel = panel - {r["clave_publicacion"] for r in registros}
        if validos >= maximo and not faltan_panel:
            break
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
        for t in tarjetas:
            envio = t["envio"] or ""
            registros.append(completar({
                "tienda": "cyberpuerta", "categoria": categoria,
                "fuente": "listado_selenium", "cobertura": "listado_ordenado",
                "fecha_extraccion": fecha, "url_origen": url, "url_producto": t["url_producto"],
                "posicion": len(registros) + 1,
                "id_producto": None, "sku_id": None, "sku_orden": None, "gtin": t["gtin"],
                "modelo": t["modelo"], "nombre": t["nombre"], "marca": t["marca"],
                "vendedor": "Cyberpuerta", "vendedor_id": "cyberpuerta", "vendedor_predeterminado": True,
                "categoria_tienda": t["categoria"],
                "precio_actual": a_numero(t["precio_dom"]) or a_numero(t["precio_ld"]),
                "precio_lista": a_numero(t["precio_lista"]),
                "descuento_anunciado_pct": a_numero(t["descuento"]),
                "costo_envio": 0.0 if "gratis" in envio.lower() else a_numero(envio),
                "stock_piezas": piezas(t["stock_texto"]),
                "stock_texto": t["stock_texto"],
                "disponible": None,
                "disponibilidad": (t["disponibilidad"] or "").rsplit("/", 1)[-1] or None,
                "especificaciones": json.dumps(t["specs"], ensure_ascii=False) if t["specs"] else None,
            }, corrida, vistos))
        validos = sum(r["incluido"] for r in registros)
        print(f"  página {pagina}: {len(registros)} filas, {validos} válidas")
        if len(tarjetas) < 24:  # última página
            break
        pagina += 1
        pausa()
    faltan_panel = panel - {r["clave_publicacion"] for r in registros}
    if panel:
        print(f"  panel: {len(panel) - len(faltan_panel)}/{len(panel)} publicaciones encontradas en el listado")
    return registros


# -------------------------------------------------------------------- Elektra

def pedir_api(sesion, params):
    r = sesion.get(API_ELEKTRA, params=params, timeout=30)
    if r.status_code in (403, 429):
        raise BloqueoDetectado(f"API respondió {r.status_code}")
    r.raise_for_status()
    total = int(r.headers.get("resources", "0-0/0").rsplit("/", 1)[-1])
    return r.json(), total, r.url


def filas_elektra(producto, categoria, posicion, url_origen, fecha):
    """Una fila por oferta (SKU x vendedor) de una ficha del catálogo."""
    especificaciones = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                        for k, v in producto.items() if k in (producto.get("allSpecifications") or [])}
    categoria_tienda = (producto.get("categories") or ["//"])[0].strip("/").rsplit("/", 1)[-1]
    modelo = (producto.get("Modelo") or [None])[0]
    # sku_orden 0 es la variante que muestra el listado web; sirve para empatar con extracciones anteriores
    for sku_orden, item in enumerate(producto.get("items", [])):
        for s in item.get("sellers", []):
            o = s.get("commertialOffer", {})
            precio, lista = o.get("Price"), o.get("ListPrice")
            cantidad = o.get("AvailableQuantity")
            yield {
                "tienda": "elektra", "categoria": categoria,
                "fuente": "api_catalogo", "cobertura": "censo_categoria",
                "fecha_extraccion": fecha, "url_origen": url_origen, "url_producto": producto.get("link"),
                "posicion": posicion,
                "id_producto": producto.get("productId"), "sku_id": item.get("itemId"), "sku_orden": sku_orden,
                "gtin": item.get("ean"),
                "modelo": modelo, "nombre": producto.get("productName"), "marca": producto.get("brand"),
                "vendedor": s.get("sellerName"), "vendedor_id": s.get("sellerId"),
                "vendedor_predeterminado": s.get("sellerDefault"),
                "categoria_tienda": categoria_tienda,
                "precio_actual": precio, "precio_lista": lista,
                # Mismo cálculo que la etiqueta "-x%" del listado (verificado en el piloto: coinciden siempre)
                "descuento_anunciado_pct": round(100 * (1 - precio / lista)) if precio and lista and lista > precio else None,
                "costo_envio": None,
                # AvailableQuantity viene topado (0, 1, 10, 100, 99999): sirve como disponibilidad, no como piezas
                "stock_piezas": None,
                "stock_texto": f"AvailableQuantity={cantidad}",
                "disponible": bool(o.get("IsAvailable")) and (cantidad or 0) > 0,
                "disponibilidad": "InStock" if o.get("IsAvailable") else "OutOfStock",
                "especificaciones": json.dumps(especificaciones, ensure_ascii=False) if especificaciones else None,
            }


def extraer_elektra(categoria, corrida):
    sesion = requests.Session()
    sesion.headers["User-Agent"] = AGENTE_API
    registros, vistos, posicion = [], set(), 0
    for ruta in CATEGORIAS_ELEKTRA[categoria]:
        desde, total, fichas = 0, 0, 0
        while True:
            params = {"fq": f"C:/{ruta}/", "_from": desde, "_to": desde + LOTE_API - 1, "O": "OrderByNameASC"}
            productos, total_lote, url = pedir_api(sesion, params)
            # El total del encabezado a veces llega en 0 en el último lote: se conserva el mayor visto
            total = max(total, total_lote)
            fecha = ahora_iso()
            for p in productos:
                posicion += 1
                fichas += 1
                for fila in filas_elektra(p, categoria, posicion, url, fecha):
                    registros.append(completar(fila, corrida, vistos))
            desde += LOTE_API
            if not productos or desde >= total:
                break
            time.sleep(PAUSA_API)
        aviso = "" if fichas == total else f" (el catálogo anunció {total})"
        print(f"  categoría {ruta}: {fichas} fichas{aviso}")
    validos = sum(r["incluido"] for r in registros)
    print(f"  {posicion} fichas, {len(registros)} ofertas, {validos} ofertas válidas")
    return registros


# ----------------------------------------------------------------- Ejecución

def guardar(registros, tienda, categoria, inicio):
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = DIR_SALIDA / f"{inicio:%Y-%m-%d_%H%M}_{tienda}_{categoria}.csv"
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(registros)
    return ruta


def sha256(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def anotar_corrida(corrida, tienda, categoria, registros, segundos, estado, ruta=None):
    """Bitácora con el archivo y su huella: permite comprobar que cada CSV tiene su corrida."""
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    nuevo = not REGISTRO_CORRIDAS.exists()
    try:
        with open(REGISTRO_CORRIDAS, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["corrida_id", "fecha_fin", "tienda", "categoria", "archivo", "filas",
                            "filas_incluidas", "segundos", "estado", "sha256"])
            w.writerow([corrida["corrida_id"], ahora_iso(), tienda, categoria,
                        ruta.name if ruta else "", len(registros), sum(r["incluido"] for r in registros),
                        round(segundos), estado, sha256(ruta) if ruta else ""])
    except PermissionError:
        # Pasa si el archivo está abierto en Excel; los datos ya se guardaron.
        print(f"  aviso: no se pudo escribir {REGISTRO_CORRIDAS.name} (¿abierto en Excel?)")


def resumen(registros, segundos):
    n = len(registros)
    validos = sum(r["incluido"] for r in registros)
    motivos = {}
    for r in registros:
        if r["motivo_exclusion"]:
            motivos[r["motivo_exclusion"]] = motivos.get(r["motivo_exclusion"], 0) + 1
    print(f"  = {n} filas, {validos} válidas, {segundos:.0f} s; excluidas: {motivos or 'ninguna'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tiendas", nargs="+", choices=["cyberpuerta", "elektra"], default=["cyberpuerta", "elektra"])
    p.add_argument("--categorias", nargs="+", choices=["laptops", "tablets"], default=["laptops", "tablets"])
    p.add_argument("--max", type=int, default=300, help="fichas válidas por categoría en Cyberpuerta (default 300)")
    p.add_argument("--max-paginas", type=int, default=30, help="tope de páginas de Cyberpuerta por categoría")
    p.add_argument("--visible", action="store_true", help="mostrar el navegador")
    p.add_argument("--salida", type=Path, help="carpeta de salida (default data/raw); útil para pruebas")
    args = p.parse_args()

    global DIR_SALIDA, REGISTRO_CORRIDAS
    if args.salida:
        DIR_SALIDA = args.salida.resolve()
        REGISTRO_CORRIDAS = DIR_SALIDA / "registro_corridas.csv"

    inicio_corrida = datetime.now()
    corrida = {"corrida_id": inicio_corrida.strftime("%Y%m%dT%H%M%S"), "fecha_corrida": f"{inicio_corrida:%Y-%m-%d}"}
    driver = crear_driver(args.visible) if "cyberpuerta" in args.tiendas else None
    try:
        for tienda in args.tiendas:
            for categoria in args.categorias:
                print(f"\n>> {tienda} / {categoria}")
                inicio = time.time()
                try:
                    if tienda == "cyberpuerta":
                        registros = extraer_cyberpuerta(driver, categoria, args.max, corrida, args.max_paginas)
                    else:
                        registros = extraer_elektra(categoria, corrida)
                except BloqueoDetectado as e:
                    # Ante un bloqueo se detiene toda la tienda: no se reintenta ni se evade.
                    print(f"  BLOQUEO: {e}. Se detiene {tienda}.")
                    anotar_corrida(corrida, tienda, categoria, [], time.time() - inicio, f"bloqueo: {e}")
                    break
                except (TimeoutException, WebDriverException, requests.RequestException) as e:
                    print(f"  ERROR: {e.__class__.__name__}. Se omite.")
                    anotar_corrida(corrida, tienda, categoria, [], time.time() - inicio, f"error: {e.__class__.__name__}")
                    continue
                ruta = guardar(registros, tienda, categoria, inicio_corrida)
                resumen(registros, time.time() - inicio)
                anotar_corrida(corrida, tienda, categoria, registros, time.time() - inicio, "ok", ruta)
                print(f"  guardado en {ruta}")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
