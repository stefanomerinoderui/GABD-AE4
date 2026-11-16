"""Vista materializada `resumen_envios_mensual` y su refresco."""

import logging
import re
import time
from pathlib import Path

import psycopg

from logistica.conexiones import conectar_pg

log = logging.getLogger(__name__)

SQL_RESUMEN = Path(__file__).resolve().parents[2] / "postgres" / "centro" / "05_resumen_envios.sql"
VISTA = "resumen_envios_mensual"


def sentencias_de(texto: str) -> list[str]:
    """Parte un script SQL en sentencias, descartando comentarios (pueden contener ';')."""
    sin_comentarios = "\n".join(
        linea for linea in texto.splitlines() if not linea.strip().startswith("--")
    )
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


def modo_de_refresco(poblada: bool) -> str:
    """CONCURRENTLY solo es válido si la vista ya tiene datos; la primera carga es completa."""
    return "concurrente" if poblada else "completo"


def asegurar_vista(conexion: psycopg.Connection) -> None:
    """Crea la vista y su índice único si faltan (idempotente)."""
    for sentencia in sentencias_de(SQL_RESUMEN.read_text(encoding="utf-8")):
        conexion.execute(sentencia)


def refrescar(*, lock_timeout_s: int = 30) -> dict:
    """Refresca la vista; devuelve modo, duración y filas.

    Usa autocommit porque CONCURRENTLY no puede correr dentro de un bloque de
    transacción. Si un fragmento regional no responde, el refresco falla y la
    vista conserva su contenido anterior (comportamiento CP).
    """
    if not re.fullmatch(r"\d+", str(lock_timeout_s)):
        raise ValueError(f"lock_timeout_s no válido: {lock_timeout_s!r}")
    with conectar_pg("centro", autocommit=True) as conexion:
        asegurar_vista(conexion)
        poblada = conexion.execute(
            "SELECT ispopulated FROM pg_matviews WHERE matviewname = %s", (VISTA,)
        ).fetchone()["ispopulated"]
        modo = modo_de_refresco(poblada)
        # Evita apilar refrescos si uno anterior sigue corriendo.
        conexion.execute(f"SET lock_timeout = '{lock_timeout_s}s'")
        opcion = "CONCURRENTLY " if poblada else ""
        inicio = time.perf_counter()
        conexion.execute(f"REFRESH MATERIALIZED VIEW {opcion}{VISTA}")
        ms = round((time.perf_counter() - inicio) * 1000, 1)
        filas = conexion.execute(f"SELECT count(*) AS n FROM {VISTA}").fetchone()["n"]
    log.info("Vista %s refrescada (%s) en %s ms", VISTA, modo, ms)
    return {"modo": modo, "ms": ms, "filas": filas}
