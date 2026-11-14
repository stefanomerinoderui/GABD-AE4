"""Fábricas de conexiones a los nodos PostgreSQL y al anillo Cassandra."""

from functools import lru_cache

import psycopg
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile, Session
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy
from cassandra.query import dict_factory
from psycopg.rows import dict_row

from logistica import config


def conectar_pg(nodo: str, *, timeout_conexion: int = 5, **opciones) -> psycopg.Connection:
    """Abre una conexión a un nodo PostgreSQL: 'centro', 'norte', 'sur' o 'dw'.

    Las filas se devuelven como diccionarios. `opciones` se pasa a
    `psycopg.connect` (por ejemplo `autocommit=True`).
    """
    if nodo not in config.HOSTS_PG:
        raise ValueError(f"Nodo desconocido: {nodo!r}. Válidos: {tuple(config.HOSTS_PG)}")

    hosts = config.HOSTS_PG[nodo]
    parametros = {
        "host": hosts,
        "dbname": config.DW_BASE if nodo == "dw" else config.PG_BASE,
        "user": config.PG_USUARIO,
        "password": config.PG_CLAVE,
        "connect_timeout": timeout_conexion,
        "row_factory": dict_row,
    }
    if "," in hosts:
        parametros["target_session_attrs"] = "read-write"
    return psycopg.connect(**parametros, **opciones)


@lru_cache(maxsize=1)
def sesion_cassandra() -> Session:
    """Sesión compartida contra el anillo de Cassandra.

    Las consultas usan nombres calificados (``tracking.tabla``), no ``USE``.

    Se listan los tres nodos como puntos de contacto: basta con que uno
    responda para descubrir el resto del anillo.
    """
    perfil = ExecutionProfile(
        load_balancing_policy=TokenAwarePolicy(
            DCAwareRoundRobinPolicy(local_dc=config.CASSANDRA_DC)
        ),
        row_factory=dict_factory,
        request_timeout=15,
    )
    cluster = Cluster(
        contact_points=config.CASSANDRA_HOSTS,
        execution_profiles={EXEC_PROFILE_DEFAULT: perfil},
        protocol_version=5,
    )
    return cluster.connect()
