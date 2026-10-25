# Validación de datos y panel de seguimiento

## Archivos originales

| Archivo | Fuente | Filas | Incluidas | Duplicados | Precio no válido | Bitácora |
|---|---|---|---|---|---|---|
| 2026-10-23_2345_cyberpuerta_laptops.csv | listado_selenium | 300 | 300 | 0 | 0 | ok |
| 2026-10-23_2345_cyberpuerta_tablets.csv | listado_selenium | 300 | 300 | 0 | 0 | ok |
| 2026-10-23_2345_elektra_laptops.csv | listado_selenium | 300 | 274 | 0 | 0 | ok |
| 2026-10-23_2345_elektra_tablets.csv | listado_selenium | 300 | 176 | 0 | 0 | sin_entrada |
| 2026-10-25_1206_cyberpuerta_laptops.csv | listado_selenium | 300 | 300 | 0 | 0 | ok |
| 2026-10-25_1206_cyberpuerta_tablets.csv | listado_selenium | 296 | 296 | 0 | 0 | ok |
| 2026-10-25_1206_elektra_laptops.csv | listado_selenium | 300 | 260 | 0 | 0 | ok |
| 2026-10-25_1206_elektra_tablets.csv | listado_selenium | 300 | 190 | 0 | 0 | ok |

## Exclusiones por motivo

- elektra / laptops / categoria_tienda_fuera: 49
- elektra / laptops / nombre_indica_otro_producto: 17
- elektra / tablets / categoria_tienda_fuera: 50
- elektra / tablets / nombre_indica_otro_producto: 182
- elektra / tablets / publicacion_de_prueba: 2

## Panel

- cyberpuerta / laptops: 300 publicaciones fijadas el 2026-10-23
- cyberpuerta / tablets: 300 publicaciones fijadas el 2026-10-23
- elektra / laptops: 274 publicaciones fijadas el 2026-10-23
- elektra / tablets: 176 publicaciones fijadas el 2026-10-23

## Estado del panel por fecha

| Tienda | Categoría | Fecha | Cobertura | Observadas | Excluidas ese día | Ausentes | Cambiaron de precio |
|---|---|---|---|---|---|---|---|
| cyberpuerta | laptops | 2026-10-23 | listado_ordenado | 300 | 0 | 0 | 0 |
| cyberpuerta | laptops | 2026-10-25 | listado_ordenado | 283 | 0 | 17 | 217 |
| cyberpuerta | tablets | 2026-10-23 | listado_ordenado | 300 | 0 | 0 | 0 |
| cyberpuerta | tablets | 2026-10-25 | listado_ordenado | 275 | 0 | 25 | 56 |
| elektra | laptops | 2026-10-23 | muestra_listado_aleatorio | 274 | 0 | 0 | 0 |
| elektra | laptops | 2026-10-25 | muestra_listado_aleatorio | 109 | 0 | 165 | 13 |
| elektra | tablets | 2026-10-23 | muestra_listado_aleatorio | 176 | 0 | 0 | 0 |
| elektra | tablets | 2026-10-25 | muestra_listado_aleatorio | 128 | 0 | 48 | 36 |

Altas (publicaciones válidas nuevas después del día base): 251

Las ausencias se interpretan según la cobertura de ese día: en un censo de categoría indican probable baja; en un listado ordenado, que la publicación quedó fuera del rango extraído; en la muestra del listado web de Elektra, solo que no salió en esa carga.

Grupos marca+modelo con más de una publicación (posibles variantes, no se fusionan): 71
