# Precios antes del Buen Fin 2026

Proyecto de web scraping que sigue día a día los precios, precios tachados, descuentos
anunciados y disponibilidad de laptops y tablets en **Cyberpuerta** y **Elektra**,
entre el 23 de octubre y el 8 de noviembre de 2026, semanas previas al Buen Fin
(13–17 de noviembre).

## Objetivo

Comprobar, con las mismas publicaciones observadas diariamente:

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

1. Extracción del día (~10 min). No abras en Excel los archivos de `data/raw/` mientras corre:

   ```bash
   python scraping/extraer_precios.py
   ```

2. Validación y panel (unos segundos; se puede repetir cuantas veces se quiera):

   ```bash
   python scraping/preparar_panel.py
   ```

Prueba rápida sin tocar `data/raw` (navegador visible, salida en otra carpeta):

```bash
python scraping/extraer_precios.py --tiendas cyberpuerta --categorias tablets --max 30 --max-paginas 2 --visible --salida prueba
```

En Windows también se puede hacer doble clic en `ejecutar_diario.bat`, que guarda la salida
en `data/raw/log_extraccion.txt`.

## Fuentes y por qué cada método

| Tienda | Método | Motivo |
|---|---|---|
| Cyberpuerta | Selenium sobre el listado de categoría | El HTML inicial trae ~16 de 24 productos por página (el resto se carga al desplazarse) y el precio se dibuja con un componente animado cuyo valor no está en el texto. El orden del listado es estable entre días (~93 % de reaparición). |
| Elektra | Catálogo público (API VTEX permitida en su `robots.txt`) por categoría exacta | El listado web se **reordena en cada carga** (en dos cargas seguidas solo coincidieron 72 de 120 laptops), así que "los primeros 300" no son las mismas publicaciones cada día. El catálogo devuelve la categoría completa en orden fijo (~1,400 laptops y ~370 tablets en ~36 peticiones), con todas las ofertas por vendedor. En una prueba, su precio coincidió con el del listado web en 259 de 260 laptops. |

El 23 y 25 de octubre Elektra se extrajo del listado web de búsqueda; esos archivos se conservan tal cual
y se marcan con cobertura `muestra_listado_aleatorio`.

## Salida

`data/raw/` (originales, nunca se modifican): un CSV por tienda y categoría por corrida
(`AAAA-MM-DD_HHMM_<tienda>_<categoria>.csv`) y la bitácora `registro_corridas.csv`
(archivo, filas, filas incluidas, estado y huella SHA-256). Las corridas del 23 y 25 de octubre
están en `registro_ejecuciones.csv` (formato anterior; falta la de tablets de Elektra del 23,
que no se anotó porque el archivo estaba abierto en Excel).

`data/procesado/` (se regenera con `preparar_panel.py`):

| Archivo | Contenido |
|---|---|
| `observaciones.csv` | Todas las filas originales con archivo y fila de origen, claves, `incluido` y `motivo_exclusion` |
| `panel.csv` | Publicaciones que se siguen: hasta 300 por tienda y categoría, fijadas el primer día |
| `panel_estado.csv` | Estado de cada publicación del panel en cada fecha (observada, excluida ese día o ausente) y cambio de precio |
| `altas.csv` | Publicaciones válidas que aparecen después del día base |

`data/validacion/`: `validacion_archivos.csv` y `reporte_validacion.md` (conteos, duplicados, precios
no válidos, faltantes, correspondencia con la bitácora).

### Claves

| Nivel | Clave | Uso |
|---|---|---|
| Producto físico (candidato) | marca + modelo normalizados | Solo agrupa publicaciones parecidas; **no** deduplica (puede haber variantes o paquetes) |
| Publicación | Elektra: `productId`; Cyberpuerta: ruta de la URL | Ficha de la tienda |
| Oferta | publicación + SKU + vendedor | Una ficha de Elektra puede tener variantes y varios vendedores |
| Seguimiento (panel) | publicación + vendedor, variante principal | Empata los listados antiguos (sin SKU) con el catálogo |
| Observación | oferta + corrida | Una fila por oferta y extracción |

### Exclusiones (`motivo_exclusion`)

`precio_no_valido` (precio 0 o vacío: en Elektra es una oferta sin existencias, no un precio),
`oferta_no_disponible`, `nombre_indica_otro_producto` (fundas, teclados, celulares… aunque la tienda
los liste en la categoría), `categoria_tienda_fuera`, `publicacion_de_prueba`, `duplicado_en_corrida`.
Las filas excluidas se conservan en `observaciones.csv`.

## Limitaciones conocidas

- En Cyberpuerta los precios cambian casi a diario en ±1 % (probablemente por tipo de cambio). Conviene
  usar un umbral antes de llamar "cambio de precio" a una variación.
- `AvailableQuantity` de Elektra viene topado (0, 1, 10, 100, 99999): se usa como disponibilidad, no como piezas.
- Una ausencia significa cosas distintas según la cobertura del día (ver `panel_estado.csv`).

## Ética de la extracción

Se respetan los `robots.txt` (solo listados y el catálogo público permitidos), hay pausas de 3–6 s entre
páginas y de 1.5 s entre peticiones al catálogo, y si aparece un CAPTCHA, un reto antibots o un 403/429,
la tienda se detiene en lugar de evadirlo.
