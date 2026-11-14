"""Tuning: comparación de planes de ejecución y costo de escritura de los índices.

Los experimentos se hacen sobre una tabla de prueba (``bench_envios``) en
pg-centro, con volumen suficiente para que el planificador tenga algo que
decidir; no se tocan los datos del sistema.
"""

import re
import time
from pathlib import Path

import psycopg
from psycopg import sql

from logistica.conexiones import conectar_pg

SQL_INDICES = Path(__file__).resolve().parents[2] / "postgres" / "comun" / "03_indices.sql"
TABLA_BENCH = "bench_envios"


def explicar(conexion: psycopg.Connection, consulta: str, parametros=None) -> str:
    """Plan de ejecución real (EXPLAIN ANALYZE) como texto."""
    filas = conexion.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, COSTS, TIMING OFF, SUMMARY ON) {consulta}", parametros
    ).fetchall()
    return "\n".join(f["QUERY PLAN"] for f in filas)


def tiempo_ejecucion_ms(plan: str) -> float:
    """Extrae 'Execution Time' de un plan generado por `explicar`."""
    for linea in plan.splitlines():
        if linea.startswith("Execution Time:"):
            return float(linea.split(":")[1].split()[0])
    raise ValueError("El plan no contiene 'Execution Time'")


def crear_tabla_bench(conexion: psycopg.Connection, filas: int = 500_000) -> None:
    """Tabla de prueba sin índices, cargada en orden cronológico (como en producción)."""
    conexion.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLA_BENCH)))
    conexion.execute(
        sql.SQL("CREATE TABLE {} (LIKE envios_centro INCLUDING DEFAULTS)").format(
            sql.Identifier(TABLA_BENCH)
        )
    )
    insertar_filas_bench(conexion, filas, desde_id=1)
    conexion.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(TABLA_BENCH)))


def insertar_filas_bench(conexion: psycopg.Connection, filas: int, desde_id: int) -> float:
    """Inserta `filas` envíos sintéticos; devuelve los segundos que tardó."""
    inicio = time.perf_counter()
    conexion.execute(
        sql.SQL(
            """
            INSERT INTO {tabla}
                (region, cliente_id, sucursal_origen_id, sucursal_destino_id, peso_kg,
                 distancia_km, estado, fecha_alta)
            SELECT 'centro', 1 + (n::bigint * 7919) %% 20000, 6 + n %% 5, 6 + (n + 1) %% 5,
                   1 + n %% 50, 100,
                   -- 98 por ciento cerrados: los envíos abiertos son pocos y recientes.
                   CASE WHEN n > %(total)s * 0.98 THEN 'en_transito' ELSE 'entregado' END,
                   timestamptz '2025-01-01' + n * interval '90 seconds'
            FROM generate_series(%(desde)s, %(hasta)s) AS n
            """
        ).format(tabla=sql.Identifier(TABLA_BENCH)),
        {"desde": desde_id, "hasta": desde_id + filas - 1, "total": desde_id + filas - 1},
    )
    return time.perf_counter() - inicio


def aplicar_indices(conexion: psycopg.Connection, tabla: str) -> None:
    """Ejecuta la plantilla 03_indices.sql sobre `tabla`."""
    if not re.fullmatch(r"[a-z_]+", tabla):
        raise ValueError(f"Nombre de tabla no válido: {tabla!r}")
    # Los comentarios se descartan antes de partir por ';' porque pueden contenerlo.
    sin_comentarios = "\n".join(
        linea
        for linea in SQL_INDICES.read_text(encoding="utf-8").splitlines()
        if not linea.strip().startswith("--")
    )
    for sentencia in sin_comentarios.split(";"):
        if sentencia.strip():
            conexion.execute(sentencia.replace("{tabla}", tabla))


def quitar_indices(conexion: psycopg.Connection, tabla: str) -> None:
    for sufijo in ("cliente_fecha", "abiertos", "fecha_brin"):
        conexion.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(f"{tabla}_{sufijo}"))
        )


def tamanios_indices(conexion: psycopg.Connection, tabla: str) -> list[dict]:
    return conexion.execute(
        """
        SELECT indexrelname AS indice, pg_size_pretty(pg_relation_size(indexrelid)) AS tamanio
        FROM pg_stat_user_indexes WHERE relname = %s ORDER BY pg_relation_size(indexrelid) DESC
        """,
        (tabla,),
    ).fetchall()


def costo_de_escritura(filas_existentes: int, filas_lote: int = 100_000) -> dict[str, float]:
    """Mide cuánto tarda insertar un lote con y sin los tres índices.

    Es el contrapeso del tuning: cada índice acelera lecturas pero suma trabajo
    en cada INSERT. `filas_existentes` es el tamaño actual de la tabla de prueba.
    Devuelve segundos y el sobrecosto porcentual.
    """
    with conectar_pg("centro", autocommit=True) as conexion:
        quitar_indices(conexion, TABLA_BENCH)
        sin = insertar_filas_bench(conexion, filas_lote, desde_id=filas_existentes + 1)
        aplicar_indices(conexion, TABLA_BENCH)
        con = insertar_filas_bench(conexion, filas_lote, desde_id=filas_existentes + filas_lote + 1)
    return {"sin_indices_s": sin, "con_indices_s": con, "sobrecosto_pct": (con / sin - 1) * 100}


def eliminar_tabla_bench() -> None:
    with conectar_pg("centro", autocommit=True) as conexion:
        conexion.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(TABLA_BENCH)))
