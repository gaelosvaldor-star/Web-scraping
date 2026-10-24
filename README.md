# Precios antes del Buen Fin 2026

Proyecto de web scraping que sigue día a día los precios, precios tachados, descuentos
anunciados y piezas en stock de laptops y tablets en **Cyberpuerta** y **Elektra**,
entre el 23 de octubre y el 8 de noviembre de 2026, semanas previas al Buen Fin
(13–17 de noviembre).

## Objetivo

Comprobar, con los mismos productos observados diariamente:

1. Si los precios suben en las semanas previas al Buen Fin.
2. Si los precios tachados son precios que realmente se cobran o un "descuento" permanente.
3. Si en Elektra los vendedores externos anuncian descuentos distintos a los de la propia Elektra.
4. Si el stock de Cyberpuerta baja más rápido en productos con descuento (aproximación a la demanda, no ventas exactas).

Los resultados describen asociaciones en esta muestra; no prueban intención ni causalidad.

## Requisitos

- Python 3.10 o superior
- Google Chrome instalado (Selenium descarga el chromedriver automáticamente)

```bash
pip install -r requirements.txt
```

## Cómo ejecutar

Extracción completa (laptops y tablets, 300 productos por tienda y categoría, ~10 min):

```bash
python scraping/extraer_precios.py
```

Prueba rápida con el navegador visible:

```bash
python scraping/extraer_precios.py --tiendas elektra --categorias tablets --max 30 --visible
```

En Windows también se puede hacer doble clic en `ejecutar_diario.bat`, que guarda la salida
en `data/raw/log_extraccion.txt`.

## Salida

Cada corrida crea un CSV por tienda y categoría en `data/raw/`
(`AAAA-MM-DD_HHMM_<tienda>_<categoria>.csv`). Cada fila es una observación
producto × tienda × día con, entre otras, estas columnas:

| Columna | Descripción |
|---|---|
| `url_origen` | Página del listado de donde se extrajo el registro |
| `fecha_extraccion` | Fecha y hora de la extracción (con zona horaria) |
| `url_producto` | Página del producto; identifica al producto entre días |
| `precio_actual`, `precio_lista` | Precio cobrado y precio tachado |
| `descuento_anunciado_pct` | Porcentaje que muestra la tienda |
| `stock_piezas` | Piezas en existencia (solo Cyberpuerta) |
| `vendedor` | Elektra o vendedor externo del marketplace |
| `categoria_tienda` | Categoría según la tienda; en Elektra sirve para quitar accesorios |

`data/raw/registro_ejecuciones.csv` anota cada corrida (registros obtenidos, duración, errores o bloqueos).

## Por qué Selenium

- **Cyberpuerta:** el HTML inicial trae ~16 de los 24 productos de cada página; el resto se carga al
  desplazarse. El precio se dibuja con un componente animado cuyo valor no está en el texto de la página.
- **Elektra:** los productos se agregan al pulsar "MOSTRAR MÁS"; sin ese clic solo hay unos cuantos.

## Ética de la extracción

Se respetan los `robots.txt` (solo se visitan listados permitidos), hay pausas de 3–6 s entre páginas
y, si aparece un CAPTCHA o reto antibots, la tienda se omite en lugar de evadirlo.
