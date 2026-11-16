"""ETL hacia el data warehouse (constelación de hechos).

Extrae de los dos subsistemas (PostgreSQL vía la tabla global ``envios`` de
pg-centro, y Cassandra) y carga pg-dw. Es idempotente: se puede ejecutar las
veces que haga falta sin duplicar filas (upsert por clave natural).
"""

import logging
from datetime import date

from logistica import config, tracking
from logistica.conexiones import conectar_pg

log = logging.getLogger(__name__)

MESES_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _cargar_dim_tiempo(dw, desde: date, hasta: date) -> None:
    dw.execute(
        """
        INSERT INTO dim_tiempo (tiempo_id, fecha, dia, mes, nombre_mes, trimestre, anio,
                                dia_semana, es_fin_de_semana)
        SELECT to_char(f, 'YYYYMMDD')::int, f::date, extract(day FROM f), extract(month FROM f),
               (%s::text[])[extract(month FROM f)::int], extract(quarter FROM f),
               extract(year FROM f), extract(isodow FROM f), extract(isodow FROM f) >= 6
        FROM generate_series(%s::date, %s::date, interval '1 day') AS f
        ON CONFLICT (tiempo_id) DO NOTHING
        """,
        (list(MESES_ES), desde, hasta),
    )


def _cargar_dimensiones(dw, central) -> None:
    sucursales = central.execute("SELECT region, provincia, ciudad FROM sucursales").fetchall()
    dw.cursor().executemany(
        "INSERT INTO dim_geografia (region, provincia, ciudad) "
        "VALUES (%(region)s, %(provincia)s, %(ciudad)s) ON CONFLICT DO NOTHING",
        sucursales,
    )
    vehiculos = central.execute(
        """SELECT v.id AS vehiculo_id, v.patente, v.tipo, v.capacidad_kg, s.region AS region_base
           FROM vehiculos v JOIN sucursales s ON s.id = v.sucursal_base_id"""
    ).fetchall()
    dw.cursor().executemany(
        """INSERT INTO dim_vehiculo (vehiculo_id, patente, tipo, capacidad_kg, region_base)
           VALUES (%(vehiculo_id)s, %(patente)s, %(tipo)s, %(capacidad_kg)s, %(region_base)s)
           ON CONFLICT (vehiculo_id) DO UPDATE SET tipo = EXCLUDED.tipo,
               capacidad_kg = EXCLUDED.capacidad_kg, region_base = EXCLUDED.region_base""",
        vehiculos,
    )


def _mapa_geografia(dw) -> dict[tuple, int]:
    filas = dw.execute("SELECT geografia_id, region, provincia, ciudad FROM dim_geografia")
    return {(f["region"], f["provincia"], f["ciudad"]): f["geografia_id"] for f in filas}


def _cargar_entregas(dw, central, geografia: dict, sucursal_geo: dict) -> int:
    # La consulta usa la tabla global: pg-centro lee los tres fragmentos
    # (dos de ellos por postgres_fdw) y los une con la facturación local.
    filas = central.execute(
        """
        SELECT e.id, e.sucursal_origen_id, e.sucursal_destino_id, e.vehiculo_id, e.peso_kg,
               e.distancia_km, e.lluvia_mm, e.indice_trafico, e.fecha_entrega,
               extract(hour FROM e.fecha_alta)::int AS hora_despacho,
               extract(epoch FROM e.fecha_entrega - e.fecha_alta) / 3600 AS horas_entrega,
               f.monto
        FROM envios AS e LEFT JOIN facturas AS f ON f.envio_id = e.id
        WHERE e.estado = 'entregado'
        """
    ).fetchall()
    parametros = [
        {
            **f,
            "tiempo_id": int(f["fecha_entrega"].strftime("%Y%m%d")),
            "geo_origen": sucursal_geo[f["sucursal_origen_id"]],
            "geo_destino": sucursal_geo[f["sucursal_destino_id"]],
        }
        for f in filas
    ]
    dw.cursor().executemany(
        """
        INSERT INTO hechos_entregas
            (envio_id, tiempo_id, geografia_origen_id, geografia_destino_id, vehiculo_id,
             hora_despacho, peso_kg, distancia_km, lluvia_mm, indice_trafico, horas_entrega, monto)
        VALUES (%(id)s, %(tiempo_id)s, %(geo_origen)s, %(geo_destino)s, %(vehiculo_id)s,
                %(hora_despacho)s, %(peso_kg)s, %(distancia_km)s, %(lluvia_mm)s,
                %(indice_trafico)s, %(horas_entrega)s, %(monto)s)
        ON CONFLICT (envio_id, tiempo_id) DO UPDATE SET horas_entrega = EXCLUDED.horas_entrega,
            monto = EXCLUDED.monto
        """,
        parametros,
    )
    return len(parametros)


def _meses(desde: date, hasta: date):
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        yield f"{anio:04d}-{mes:02d}"
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def _cargar_incidentes(dw, sucursal_geo: dict, desde: date, hasta: date) -> int:
    filas = [
        {**incidente, "tiempo_id": int(incidente["ts"].strftime("%Y%m%d"))}
        for region in config.REGIONES
        for mes in _meses(desde, hasta)
        for incidente in tracking.incidentes_del_mes(region, mes)
    ]
    sin_sucursal = [f for f in filas if f["sucursal_id"] not in sucursal_geo]
    if sin_sucursal:
        # Sin sucursal no hay dimensión Geografía: se omiten en vez de abortar la carga.
        log.warning("%s incidentes sin sucursal conocida omitidos del DW", len(sin_sucursal))
        filas = [f for f in filas if f["sucursal_id"] in sucursal_geo]
    dw.cursor().executemany(
        """
        INSERT INTO hechos_incidentes
            (incidente_id, tiempo_id, geografia_id, vehiculo_id, tipo, demora_min, lat, lon)
        VALUES (%(id_incidente)s, %(tiempo_id)s, %(geografia_id)s, %(vehiculo_id)s,
                %(tipo)s, %(demora_min)s, %(lat)s, %(lon)s)
        ON CONFLICT (incidente_id, tiempo_id) DO NOTHING
        """,
        [{**f, "geografia_id": sucursal_geo[f["sucursal_id"]]} for f in filas],
    )
    return len(filas)


def ejecutar_etl(desde: date = date(2025, 1, 1), hasta: date | None = None) -> dict[str, int]:
    """Carga completa de dimensiones y hechos. Devuelve filas procesadas por tabla."""
    hasta = hasta or date.today()
    with conectar_pg("centro") as central, conectar_pg("dw") as dw:
        _cargar_dim_tiempo(dw, desde, hasta)
        _cargar_dimensiones(dw, central)
        geografia = _mapa_geografia(dw)
        sucursal_geo = {
            s["id"]: geografia[(s["region"], s["provincia"], s["ciudad"])]
            for s in central.execute("SELECT id, region, provincia, ciudad FROM sucursales")
        }
        entregas = _cargar_entregas(dw, central, geografia, sucursal_geo)
        incidentes = _cargar_incidentes(dw, sucursal_geo, desde, hasta)
    log.info("ETL completo: %s entregas, %s incidentes", entregas, incidentes)
    return {"hechos_entregas": entregas, "hechos_incidentes": incidentes}
