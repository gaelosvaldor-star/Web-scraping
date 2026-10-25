"""Reglas compartidas por el extractor y la preparación del panel.

Claves (de más general a más específica):

- producto físico (candidato): marca + modelo normalizados. Solo sirve para
  agrupar publicaciones parecidas; NO se usa para deduplicar, porque un mismo
  modelo puede tener variantes (RAM, color, paquete) o varias publicaciones.
- publicación: tienda + identificador estable de la ficha.
  Elektra: productId. Cyberpuerta: ruta de la URL del producto.
- oferta: publicación + vendedor. En Elektra una ficha puede tener varios vendedores.
- observación: oferta + corrida (fecha y hora de la extracción).
"""

import re
import unicodedata
from urllib.parse import urlsplit

# Categorías de la tienda aceptadas para cada categoría del estudio (Elektra).
CATEGORIAS_TIENDA_VALIDAS = {
    "laptops": {"laptops", "gaming", "2-en-1", "reacondicionados"},
    "tablets": {"tablets"},
}

# Si el nombre empieza así, la ficha es otro tipo de producto aunque la tienda
# la haya listado en la categoría (p. ej. "Funda para iPad" en Tablets).
PRIMERAS_PALABRAS_AJENAS = {
    "funda", "fundas", "mica", "micas", "protector", "teclado", "mouse", "cargador",
    "cable", "estuche", "mochila", "maletin", "bolsa", "soporte", "base", "lapiz",
    "stylus", "pluma", "smartwatch", "reloj", "audifonos", "celular", "smartphone",
    "router", "impresora", "monitor", "cpu", "bocina", "adaptador", "hub", "memoria",
    "disco", "carcasa", "pelicula", "cristal", "kindle", "lector", "camara", "consola",
    "pantalla", "refaccion",
}
FRASES_AJENAS = ("e reader", "lector de libros", "de escritorio", "all in one", "smart folio")
# "Reacondicionados" de Elektra mezcla laptops con celulares: ahí se exige un término de laptop.
TERMINOS_LAPTOP = ("laptop", "notebook", "chromebook", "macbook", "matebook", "ideapad",
                   "thinkpad", "vivobook", "zenbook", "inspiron", "latitude", "pavilion", "victus")


def normalizar(texto):
    """Minúsculas, sin acentos ni signos, espacios simples."""
    if texto is None or (isinstance(texto, float) and texto != texto):
        return ""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return t.strip()


def clave_publicacion(tienda, url_producto=None, id_producto=None):
    if tienda == "elektra" and id_producto not in (None, ""):
        return f"elektra|{str(id_producto).split('.')[0]}"
    if url_producto:
        ruta = urlsplit(str(url_producto)).path.lower().rstrip("/")
        return f"{tienda}|{ruta}"
    return None


def clave_oferta(clave_pub, vendedor, sku=None):
    """Una ficha de Elektra puede tener variantes (SKU) con precios distintos: cada una es otra oferta."""
    if not clave_pub:
        return None
    sku = "" if sku is None or (isinstance(sku, float) and sku != sku) else str(sku).split(".")[0]
    return f"{clave_pub}|{sku}|{normalizar(vendedor)}" if sku else f"{clave_pub}|{normalizar(vendedor)}"


def clave_producto_candidata(marca, modelo):
    m, mo = normalizar(marca), normalizar(modelo)
    return f"{m}|{mo}" if m and mo else None


def motivo_exclusion(categoria, nombre, categoria_tienda, tienda, precio_actual,
                     disponible=True, vendedor=None):
    """Devuelve None si la fila es válida para el estudio, o el motivo por el que se excluye."""
    if precio_actual is None or precio_actual != precio_actual or precio_actual <= 0:
        # Un precio 0 en Elektra corresponde a una oferta sin existencias, no a un precio real.
        return "precio_no_valido"
    if disponible is False:
        return "oferta_no_disponible"
    nombre_n = normalizar(nombre)
    if not nombre_n:
        return "sin_nombre"
    if "prueba" in normalizar(vendedor).split() or nombre_n.startswith("prueba"):
        return "publicacion_de_prueba"
    if nombre_n.split()[0] in PRIMERAS_PALABRAS_AJENAS or any(f in nombre_n for f in FRASES_AJENAS):
        return "nombre_indica_otro_producto"
    if tienda == "elektra":
        cat = normalizar(categoria_tienda).replace(" ", "-")
        if cat not in CATEGORIAS_TIENDA_VALIDAS[categoria]:
            return "categoria_tienda_fuera"
        if cat == "reacondicionados" and not any(t in nombre_n for t in TERMINOS_LAPTOP):
            return "nombre_indica_otro_producto"
    return None


def condicion(nombre, categoria_tienda):
    texto = normalizar(f"{nombre} {categoria_tienda}")
    return "reacondicionado" if "reacondicionad" in texto or "renovad" in texto else "nuevo"


def es_paquete(nombre):
    """Combos y kits (tablet + accesorios) son ofertas distintas de la tablet sola."""
    n = normalizar(nombre)
    return n.startswith(("combo", "kit", "paquete")) or " + " in str(nombre or "")
