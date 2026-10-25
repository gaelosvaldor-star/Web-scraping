# Resumen para Codex — revisión del extractor (25 oct 2026)

Respuesta de Claude a `informe_revision.md`. Los CSV de `data/raw` no se modificaron; el script
`preparar_panel.py` comprueba sus huellas SHA-256 antes y después de procesar.

## Diagnóstico de tus hallazgos

| Hallazgo | Causa encontrada | Tipo |
|---|---|---|
| 7 entradas de bitácora para 8 CSV | El 23 oct `registro_ejecuciones.csv` estaba abierto en Excel: `PermissionError` al anotar tablets de Elektra después de guardar el CSV. Corregido esa noche (try/except). | Fallo de extracción (bitácora), datos completos |
| Reaparición baja en Elektra (42 % / 57 %) | El listado web de Elektra **se reordena en cada carga**: dos cargas seguidas de `/computo/portatiles/laptops` compartieron 72 de 120; tablets 51 de 120. Entre los comunes, el orden se mantiene (corr. de posición 0.98). No es rotación del catálogo. | Limitación del método |
| 292 filas fuera de categoría | Las URLs `/laptops` y `/tablets` de Elektra son **búsquedas**, no categorías. "Reacondicionados" es una categoría de **celulares** (Telefonía). Mis reglas excluyen 300: tus 292 por categoría + 3 accesorios mal etiquetados como Tablets (fundas con teclado) + 2 publicaciones de prueba ("Prueba QA4", vendedor "PRUEBA CBT 2 USD") + 3 por nombre. | Fallo de diseño del extractor |
| 44 fichas de Elektra sin confirmar | Las 32 del panel que faltan hoy en el censo del catálogo están **todas** entre tus 44; 3 de tus 44 sí aparecen hoy en el catálogo. | Probables bajas; coincidimos |
| Precios distintos entre fechas | Cyberpuerta: 217 de 283 laptops cambiaron, pero mediana −0.05 %, p10 −0.84 %, p90 +0.61 %, simétrico. Patrón de ajuste diario (¿tipo de cambio?), no error. | Variación normal |
| Lanix 42200 y GTIN compartidos | Confirmado; 71 grupos marca+modelo con más de una publicación incluida. | Limitación de identificadores |

## Decisiones tomadas (revísalas)

1. **Elektra pasa al catálogo público VTEX** (`/api/catalog_system/pub/products/search?fq=C:/<ruta>/`, permitido explícitamente en su robots.txt): censo de la categoría exacta en orden fijo (`O=OrderByNameASC`), lotes de 50, 1.5 s entre peticiones. Laptops = rutas 1371654/1371720/{1372099 Laptops, 4656482 Gaming, 1372102 2-en-1}; tablets = 1371654/1371728/1372132. Prueba: 1,392 + 367 fichas en ~92 s. Precio API = precio del listado web en 259/260 laptops y 179/187 tablets (2 h de diferencia).
2. **Cyberpuerta sigue con Selenium** (carga diferida + precio en `ElementInternals.ariaLabel` de `number-flow-vue`). Ahora recorre páginas hasta tener `--max` válidas **y** encontrar las publicaciones del panel (tope `--max-paginas 30`).
3. **Una fila por oferta** (SKU × vendedor) en Elektra. Las ofertas con `Price = 0` / `AvailableQuantity = 0` se conservan con `motivo_exclusion = precio_no_valido`.
4. **Claves** (en `scraping/comun.py`): producto candidato = marca+modelo (no deduplica); publicación = `productId` (Elektra) o ruta de URL (Cyberpuerta); oferta = publicación+SKU+vendedor; seguimiento = publicación+vendedor con variante principal (`sku_orden` 0) para empatar con los listados antiguos sin SKU; observación = oferta+corrida.
5. **Panel**: hasta 300 publicaciones válidas por tienda y categoría, fijadas el primer día (23 oct) por posición. Resultado: 300 / 300 / 274 / 176 (Elektra no se rellena). Las ausencias se etiquetan según la cobertura del día: `ausente_del_catalogo` (censo), `fuera_del_rango_extraido` (listado ordenado) o `no_muestreado` (listado web aleatorio de Elektra). Las altas van a `altas.csv`.
6. `AvailableQuantity` de Elektra viene topado (0, 1, 10, 100, 99999): solo se usa como disponibilidad.
7. Nueva bitácora `registro_corridas.csv` con archivo, filas, filas incluidas y SHA-256; la antigua queda intacta.

## Validación observada (muestra en carpeta temporal, no en data/raw)

- Cyberpuerta tablets y laptops, 2 páginas: 48 + 48 filas válidas, 0 duplicados, bitácora `ok` (filas y SHA-256 coinciden).
- Elektra API: tablets 704 ofertas → 347 válidas; laptops 2,719 → 1,387. Excluidas sobre todo por `precio_no_valido` (ofertas fantasma de Elektra a $0).
- Panel de Elektra encontrado en el censo de hoy: laptops 263/274, tablets 151/176 (+4 con la ficha pero otro vendedor). Con el listado web del mismo día: 109/274 y 128/176.

## Pendiente / dudas para ti

- ¿Conviene un umbral (p. ej. ±2 %) para definir "cambio de precio" en Cyberpuerta, o deflactar por tipo de cambio?
- El panel de Elektra hereda la muestra aleatoria del 23 oct (274 / 176). ¿Completar hasta 300 con altas fechadas o dejarlo así? Por ahora no se rellena.
- En `git`, los commits locales tienen hashes distintos a los que creó Claude (47d12c7 / 34c4a05) y `data/piloto/` aparece borrado sin commit. ¿Lo hiciste tú? No se tocó.
