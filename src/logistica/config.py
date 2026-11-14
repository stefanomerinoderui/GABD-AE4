"""Topología del clúster y parámetros de conexión (leídos del entorno)."""

import os

REGIONES = ("norte", "centro", "sur")

PG_USUARIO = os.environ.get("PG_USER", "logistica")
PG_CLAVE = os.environ.get("PG_PASSWORD", "logistica_dev")
PG_BASE = os.environ.get("PG_DB", "logistica")
DW_BASE = os.environ.get("DW_DB", "dw")

# El nodo "centro" lista primario y standby: junto con
# target_session_attrs=read-write el cliente siempre llega al que esté
# aceptando escrituras, sin cambiar configuración después de un failover.
HOSTS_PG = {
    "centro": os.environ.get("PG_CENTRO_HOSTS", "pg-centro,pg-centro-replica"),
    "norte": os.environ.get("PG_NORTE_HOST", "pg-norte"),
    "sur": os.environ.get("PG_SUR_HOST", "pg-sur"),
    "dw": os.environ.get("PG_DW_HOST", "pg-dw"),
}

CASSANDRA_HOSTS = os.environ.get(
    "CASSANDRA_HOSTS", "cassandra-norte,cassandra-centro,cassandra-sur"
).split(",")
CASSANDRA_DC = "logistica"
CASSANDRA_KEYSPACE = "tracking"


def tabla_envios(region: str) -> str:
    """Nombre del fragmento físico de Envios que corresponde a una región."""
    validar_region(region)
    return f"envios_{region}"


def validar_region(region: str) -> None:
    if region not in REGIONES:
        raise ValueError(f"Región desconocida: {region!r}. Válidas: {REGIONES}")
