"""ABM y consultas del subsistema de trazabilidad (Cassandra).

La consistencia es ajustable por operación. Por defecto se usa LOCAL_ONE:
basta con que responda una réplica, lo que maximiza disponibilidad y
velocidad de ingesta a costa de consistencia inmediata (AP / BASE).
"""

import uuid
from datetime import UTC, date, datetime
from functools import cache

from cassandra import ConsistencyLevel
from cassandra.query import PreparedStatement

from logistica.conexiones import sesion_cassandra

CONSISTENCIA_POR_DEFECTO = ConsistencyLevel.LOCAL_ONE

TIPOS_EVENTO = ("ingreso_deposito", "en_transito", "en_reparto", "entregado", "incidencia")


@cache
def _preparar(cql: str) -> PreparedStatement:
    return sesion_cassandra().prepare(cql)


def _ejecutar(cql: str, parametros: tuple, consistencia: int):
    sentencia = _preparar(cql).bind(parametros)
    sentencia.consistency_level = consistencia
    return sesion_cassandra().execute(sentencia)


def anio_mes(momento: datetime | date) -> str:
    """Clave de la ventana mensual usada para particionar los incidentes."""
    return momento.strftime("%Y-%m")


# ---------------------------------------------------------------------- eventos

INSERT_EVENTO = """
    INSERT INTO tracking.eventos_por_paquete
        (id_paquete, ts, tipo, region, sucursal_id, lat, lon, detalle)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def registrar_evento(
    id_paquete: uuid.UUID,
    tipo: str,
    region: str,
    lat: float,
    lon: float,
    *,
    ts: datetime | None = None,
    sucursal_id: int | None = None,
    detalle: str | None = None,
    consistencia: int = CONSISTENCIA_POR_DEFECTO,
) -> datetime:
    """Alta de un evento de tracking. Reescribir la misma clave (id_paquete, ts)
    lo modifica: en Cassandra INSERT es un upsert."""
    if tipo not in TIPOS_EVENTO:
        raise ValueError(f"Tipo de evento desconocido: {tipo!r}. Válidos: {TIPOS_EVENTO}")
    # Cassandra guarda milisegundos: se trunca para que la clave devuelta
    # coincida exactamente con la almacenada.
    momento = ts or datetime.now(UTC)
    momento = momento.replace(microsecond=momento.microsecond // 1000 * 1000)
    _ejecutar(
        INSERT_EVENTO,
        (id_paquete, momento, tipo, region, sucursal_id, lat, lon, detalle),
        consistencia,
    )
    return momento


def historial_paquete(
    id_paquete: uuid.UUID, *, consistencia: int = CONSISTENCIA_POR_DEFECTO
) -> list[dict]:
    """Eventos de un paquete, del más reciente al más antiguo (una sola partición)."""
    return list(
        _ejecutar(
            "SELECT * FROM tracking.eventos_por_paquete WHERE id_paquete = ?",
            (id_paquete,),
            consistencia,
        )
    )


def eliminar_evento(
    id_paquete: uuid.UUID, ts: datetime, *, consistencia: int = CONSISTENCIA_POR_DEFECTO
) -> None:
    """Baja de un evento (escribe un tombstone que se propaga a las réplicas)."""
    _ejecutar(
        "DELETE FROM tracking.eventos_por_paquete WHERE id_paquete = ? AND ts = ?",
        (id_paquete, ts),
        consistencia,
    )


# ------------------------------------------------------------------- telemetría

INSERT_TELEMETRIA = """
    INSERT INTO tracking.telemetria_por_camion
        (vehiculo_id, dia, ts, lat, lon, velocidad_kmh, temperatura_c)
    VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def registrar_telemetria(
    vehiculo_id: int,
    ts: datetime,
    lat: float,
    lon: float,
    velocidad_kmh: float,
    temperatura_c: float,
    *,
    consistencia: int = CONSISTENCIA_POR_DEFECTO,
) -> None:
    _ejecutar(
        INSERT_TELEMETRIA,
        (vehiculo_id, ts.date(), ts, lat, lon, velocidad_kmh, temperatura_c),
        consistencia,
    )


def telemetria_del_dia(
    vehiculo_id: int, dia: date, *, consistencia: int = CONSISTENCIA_POR_DEFECTO
) -> list[dict]:
    return list(
        _ejecutar(
            "SELECT * FROM tracking.telemetria_por_camion WHERE vehiculo_id = ? AND dia = ?",
            (vehiculo_id, dia),
            consistencia,
        )
    )


# ------------------------------------------------------------------- incidentes

INSERT_INCIDENTE = """
    INSERT INTO tracking.incidentes_por_region
        (region, anio_mes, ts, id_incidente, tipo, demora_min,
         vehiculo_id, sucursal_id, lat, lon)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def registrar_incidente(
    region: str,
    ts: datetime,
    tipo: str,
    demora_min: int,
    lat: float,
    lon: float,
    *,
    vehiculo_id: int | None = None,
    sucursal_id: int | None = None,
    consistencia: int = CONSISTENCIA_POR_DEFECTO,
) -> uuid.UUID:
    id_incidente = uuid.uuid4()
    _ejecutar(
        INSERT_INCIDENTE,
        (
            region,
            anio_mes(ts),
            ts,
            id_incidente,
            tipo,
            demora_min,
            vehiculo_id,
            sucursal_id,
            lat,
            lon,
        ),
        consistencia,
    )
    return id_incidente


def incidentes_del_mes(
    region: str, mes: str, *, consistencia: int = CONSISTENCIA_POR_DEFECTO
) -> list[dict]:
    """Incidentes de una región en un mes 'AAAA-MM' (una sola partición)."""
    return list(
        _ejecutar(
            "SELECT * FROM tracking.incidentes_por_region WHERE region = ? AND anio_mes = ?",
            (region, mes),
            consistencia,
        )
    )
