"""Valida los CSV originales y construye el panel de seguimiento de precios.

Lee data/raw sin modificarlo y escribe:
- data/procesado/observaciones.csv  todas las filas, con claves, archivo y fila de origen,
                                    y si entran al estudio (o por qué no)
- data/procesado/panel.csv          publicaciones que se siguen (hasta --max por tienda y categoría),
                                    fijadas el primer día observado
- data/procesado/panel_estado.csv   estado de cada publicación del panel en cada fecha
- data/procesado/altas.csv          publicaciones válidas que aparecen después del día base
- data/validacion/validacion_archivos.csv y reporte_validacion.md

Uso:
    python scraping/preparar_panel.py
"""

import argparse
import hashlib
import re
from pathlib import Path

import pandas as pd

import comun

RAIZ = Path(__file__).resolve().parent.parent
DIR_RAW = RAIZ / "data" / "raw"
DIR_PROC = RAIZ / "data" / "procesado"
DIR_VAL = RAIZ / "data" / "validacion"
PATRON_ARCHIVO = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4})_(cyberpuerta|elektra)_(laptops|tablets)\.csv$")

# Qué significa no encontrar una publicación según cómo se obtuvo ese día
AUSENCIA_SEGUN_COBERTURA = {
    "censo_categoria": "ausente_del_catalogo",         # se pidió toda la categoría: probable baja
    "listado_ordenado": "fuera_del_rango_extraido",    # quizá bajó de posición; no implica baja
    "muestra_listado_aleatorio": "no_muestreado",      # el listado web de Elektra se reordena en cada carga
}


def sha256(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def leer_archivo(ruta):
    """Lleva cada CSV (formato antiguo o nuevo) al mismo esquema, sin tocar el archivo."""
    fecha, hora, tienda, categoria = PATRON_ARCHIVO.match(ruta.name).groups()
    d = pd.read_csv(ruta, dtype={"id_producto": str, "sku_id": str, "gtin": str, "vendedor_id": str})
    d["archivo"] = ruta.name
    d["fila_csv"] = d.index + 2  # +1 por el encabezado, +1 porque las hojas de cálculo cuentan desde 1
    if "corrida_id" not in d.columns:
        # Formato del 23 y 25 de octubre: listado web con Selenium
        d["corrida_id"] = f"{fecha.replace('-', '')}T{hora}00"
        d["fecha_corrida"] = fecha
        d["fuente"] = "listado_selenium"
        d["cobertura"] = "listado_ordenado" if tienda == "cyberpuerta" else "muestra_listado_aleatorio"
        if tienda == "cyberpuerta":
            d["gtin"], d["id_producto"] = d["id_producto"], None  # ahí id_producto era el GTIN
        for col in ("sku_id", "sku_orden", "vendedor_id", "vendedor_predeterminado", "disponible"):
            d[col] = None
    return d


def preparar_observaciones(archivos):
    d = pd.concat([leer_archivo(r) for r in archivos], ignore_index=True)
    d["clave_publicacion"] = [comun.clave_publicacion(t, u, i)
                              for t, u, i in zip(d.tienda, d.url_producto, d.id_producto)]
    d["clave_oferta"] = [comun.clave_oferta(p, v, s) for p, v, s in zip(d.clave_publicacion, d.vendedor, d.sku_id)]
    # Unidad del panel: publicación + vendedor (variante principal). Empata el listado
    # antiguo, que no traía SKU, con la variante 0 del catálogo.
    d["clave_seguimiento"] = [comun.clave_oferta(p, v) for p, v in zip(d.clave_publicacion, d.vendedor)]
    d["clave_producto_candidata"] = [comun.clave_producto_candidata(m, mo) for m, mo in zip(d.marca, d.modelo)]
    d["condicion"] = [comun.condicion(n, c) for n, c in zip(d.nombre, d.categoria_tienda)]
    d["es_paquete"] = d.nombre.map(comun.es_paquete)
    disponible = d.disponible.map(lambda x: None if pd.isna(x) else str(x).lower() == "true")
    d["motivo_exclusion"] = [
        comun.motivo_exclusion(c, n, ct, t, p, disp, v)
        for c, n, ct, t, p, disp, v in zip(d.categoria, d.nombre, d.categoria_tienda, d.tienda,
                                            d.precio_actual, disponible, d.vendedor)]
    principal = d.sku_orden.isna() | (pd.to_numeric(d.sku_orden, errors="coerce") == 0)
    d["variante_principal"] = principal
    # Duplicado accidental: la misma oferta dos veces en un archivo
    dup = d.motivo_exclusion.isna() & d.duplicated(["archivo", "clave_oferta"], keep="first")
    d.loc[dup, "motivo_exclusion"] = "duplicado_en_corrida"
    d["incluido"] = d.motivo_exclusion.isna()
    return d


def primera_corrida_por_dia(d):
    """Si un día se corrió dos veces, el panel usa la primera corrida (las demás siguen en observaciones)."""
    primeras = d.groupby(["tienda", "categoria", "fecha_corrida"]).corrida_id.transform("min")
    return d[d.corrida_id == primeras]


def construir_panel(d, maximo):
    d = primera_corrida_por_dia(d)
    seg = d[d.incluido & d.variante_principal]
    paneles, estados, altas = [], [], []
    for (tienda, categoria), g in seg.groupby(["tienda", "categoria"]):
        fecha_base = g.fecha_corrida.min()
        base = (g[g.fecha_corrida == fecha_base].sort_values("posicion")
                .drop_duplicates("clave_seguimiento").head(maximo))
        panel = base[["tienda", "categoria", "clave_seguimiento", "clave_publicacion", "vendedor", "nombre",
                      "marca", "modelo", "url_producto", "precio_actual", "fecha_corrida", "archivo", "fila_csv"]]
        paneles.append(panel.rename(columns={"precio_actual": "precio_base", "fecha_corrida": "fecha_base",
                                             "archivo": "archivo_base", "fila_csv": "fila_base"}))
        claves = set(panel.clave_seguimiento)
        todas = d[(d.tienda == tienda) & (d.categoria == categoria)]
        for fecha, dia in todas.groupby("fecha_corrida"):
            cobertura = dia.cobertura.iloc[0]
            por_clave = dia[dia.variante_principal].sort_values("incluido", ascending=False) \
                .drop_duplicates("clave_seguimiento").set_index("clave_seguimiento")
            for clave in claves:
                if clave in por_clave.index:
                    r = por_clave.loc[clave]
                    estado = "observado" if r.incluido else f"observado_excluido:{r.motivo_exclusion}"
                    estados.append(dict(tienda=tienda, categoria=categoria, clave_seguimiento=clave,
                                        fecha_corrida=fecha, cobertura=cobertura, estado=estado,
                                        precio_actual=r.precio_actual if r.incluido else None,
                                        precio_lista=r.precio_lista if r.incluido else None,
                                        stock_piezas=r.stock_piezas, archivo=r.archivo, fila_csv=r.fila_csv))
                else:
                    estados.append(dict(tienda=tienda, categoria=categoria, clave_seguimiento=clave,
                                        fecha_corrida=fecha, cobertura=cobertura,
                                        estado=AUSENCIA_SEGUN_COBERTURA.get(cobertura, "no_observado")))
        nuevas = g[~g.clave_seguimiento.isin(claves)].sort_values("fecha_corrida").drop_duplicates("clave_seguimiento")
        altas.append(nuevas[["tienda", "categoria", "clave_seguimiento", "fecha_corrida", "nombre", "vendedor",
                             "precio_actual", "archivo", "fila_csv"]]
                     .rename(columns={"fecha_corrida": "fecha_primera_observacion"}))
    estado = pd.DataFrame(estados).sort_values(["tienda", "categoria", "clave_seguimiento", "fecha_corrida"])
    # Cambio de precio solo entre observaciones válidas consecutivas de la misma publicación
    previo = estado.groupby("clave_seguimiento").precio_actual.transform(lambda s: s.ffill().shift())
    estado["precio_anterior"] = previo
    estado["cambio_precio"] = estado.precio_actual - previo
    return pd.concat(paneles), estado, pd.concat(altas)


def validar_archivos(d, archivos):
    """Una fila por CSV original: conteos, duplicados, precios y correspondencia con la bitácora."""
    antiguo = pd.read_csv(DIR_RAW / "registro_ejecuciones.csv") if (DIR_RAW / "registro_ejecuciones.csv").exists() else pd.DataFrame()
    nuevo = pd.read_csv(DIR_RAW / "registro_corridas.csv") if (DIR_RAW / "registro_corridas.csv").exists() else pd.DataFrame()
    filas = []
    for ruta in archivos:
        g = d[d.archivo == ruta.name]
        fecha, _, tienda, categoria = PATRON_ARCHIVO.match(ruta.name).groups()
        huella = sha256(ruta)
        if not nuevo.empty and ruta.name in set(nuevo.archivo.dropna()):
            r = nuevo[nuevo.archivo == ruta.name].iloc[-1]
            bitacora = "ok" if (r.filas == len(g) and r.sha256 == huella) else "no_coincide"
        elif not antiguo.empty:
            m = antiguo[(antiguo.tienda == tienda) & (antiguo.categoria == categoria)
                        & antiguo.fecha.str.startswith(fecha) & (antiguo.registros == len(g))]
            bitacora = "ok" if len(m) else "sin_entrada"
        else:
            bitacora = "sin_entrada"
        motivos = g.motivo_exclusion.value_counts().to_dict()
        filas.append(dict(
            archivo=ruta.name, tienda=tienda, categoria=categoria, fecha_corrida=fecha,
            fuente=g.fuente.iloc[0], cobertura=g.cobertura.iloc[0], filas=len(g),
            incluidas=int(g.incluido.sum()),
            duplicados_oferta=int(g.duplicated("clave_oferta").sum()),
            precio_no_valido=int(motivos.get("precio_no_valido", 0)),
            lista_menor_que_actual=int((g.precio_lista < g.precio_actual).sum()),
            sin_url=int(g.url_producto.isna().sum()), sin_nombre=int(g.nombre.isna().sum()),
            sin_marca=int(g.marca.isna().sum()), sin_modelo=int(g.modelo.isna().sum()),
            excluidas_por_motivo="; ".join(f"{k}={v}" for k, v in motivos.items()),
            bitacora=bitacora, sha256=huella))
    return pd.DataFrame(filas)


def escribir_reporte(val, panel, estado, altas, d):
    lineas = ["# Validación de datos y panel de seguimiento", ""]
    lineas += ["## Archivos originales", "",
               "| Archivo | Fuente | Filas | Incluidas | Duplicados | Precio no válido | Bitácora |",
               "|---|---|---|---|---|---|---|"]
    for r in val.itertuples():
        lineas.append(f"| {r.archivo} | {r.fuente} | {r.filas} | {r.incluidas} | {r.duplicados_oferta} "
                      f"| {r.precio_no_valido} | {r.bitacora} |")
    lineas += ["", "## Exclusiones por motivo", ""]
    exc = d[~d.incluido].groupby(["tienda", "categoria", "motivo_exclusion"]).size()
    lineas += [f"- {t} / {c} / {m}: {n}" for (t, c, m), n in exc.items()]
    lineas += ["", "## Panel", ""]
    for (t, c), g in panel.groupby(["tienda", "categoria"]):
        lineas.append(f"- {t} / {c}: {len(g)} publicaciones fijadas el {g.fecha_base.iloc[0]}")
    lineas += ["", "## Estado del panel por fecha", "",
               "| Tienda | Categoría | Fecha | Cobertura | Observadas | Excluidas ese día | Ausentes | Cambiaron de precio |",
               "|---|---|---|---|---|---|---|---|"]
    for (t, c, f), g in estado.groupby(["tienda", "categoria", "fecha_corrida"]):
        obs = (g.estado == "observado").sum()
        exc_dia = g.estado.str.startswith("observado_excluido").sum()
        aus = len(g) - obs - exc_dia
        cambio = (g.cambio_precio.fillna(0) != 0).sum()
        lineas.append(f"| {t} | {c} | {f} | {g.cobertura.iloc[0]} | {obs} | {exc_dia} | {aus} | {cambio} |")
    lineas += ["", f"Altas (publicaciones válidas nuevas después del día base): {len(altas)}", "",
               "Las ausencias se interpretan según la cobertura de ese día: en un censo de categoría indican "
               "probable baja; en un listado ordenado, que la publicación quedó fuera del rango extraído; en la "
               "muestra del listado web de Elektra, solo que no salió en esa carga.", ""]
    grupos = d[d.incluido & d.clave_producto_candidata.notna()].groupby(["tienda", "clave_producto_candidata"]) \
        .clave_publicacion.nunique()
    lineas.append(f"Grupos marca+modelo con más de una publicación (posibles variantes, no se fusionan): "
                  f"{(grupos > 1).sum()}")
    (DIR_VAL / "reporte_validacion.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max", type=int, default=300, help="publicaciones del panel por tienda y categoría")
    p.add_argument("--raw", type=Path, help="carpeta de CSV originales (default data/raw)")
    p.add_argument("--salida", type=Path, help="carpeta para procesado/ y validacion/ (default data/)")
    args = p.parse_args()

    global DIR_RAW, DIR_PROC, DIR_VAL
    if args.raw:
        DIR_RAW = args.raw.resolve()
    if args.salida:
        DIR_PROC, DIR_VAL = args.salida.resolve() / "procesado", args.salida.resolve() / "validacion"

    archivos = sorted(r for r in DIR_RAW.glob("*.csv") if PATRON_ARCHIVO.match(r.name))
    huellas_antes = {r.name: sha256(r) for r in archivos}
    d = preparar_observaciones(archivos)
    panel, estado, altas = construir_panel(d, args.max)
    val = validar_archivos(d, archivos)

    DIR_PROC.mkdir(parents=True, exist_ok=True)
    DIR_VAL.mkdir(parents=True, exist_ok=True)
    d.to_csv(DIR_PROC / "observaciones.csv", index=False, encoding="utf-8-sig")
    panel.to_csv(DIR_PROC / "panel.csv", index=False, encoding="utf-8-sig")
    estado.to_csv(DIR_PROC / "panel_estado.csv", index=False, encoding="utf-8-sig")
    altas.to_csv(DIR_PROC / "altas.csv", index=False, encoding="utf-8-sig")
    val.to_csv(DIR_VAL / "validacion_archivos.csv", index=False, encoding="utf-8-sig")
    escribir_reporte(val, panel, estado, altas, d)

    assert huellas_antes == {r.name: sha256(r) for r in archivos}, "un CSV original cambió durante la preparación"
    print(f"{len(archivos)} archivos, {len(d)} filas, {int(d.incluido.sum())} incluidas; "
          f"panel {len(panel)} publicaciones; altas {len(altas)}")
    print(f"reporte: {DIR_VAL / 'reporte_validacion.md'}")


if __name__ == "__main__":
    main()
