"""Corte abrupto de energía en el nodo Sur y recuperación con el WAL.

REDO   una transacción con COMMIT cuyas páginas seguían solo en memoria se reconstruye
       reaplicando el WAL (Durabilidad).
UNDO   una transacción sin COMMIT queda invisible: PostgreSQL no tiene log de undo; sus
       filas pertenecen a una transacción nunca confirmada (MVCC) y se descartan
       lógicamente, aunque su registro esté en el WAL.
"""

import subprocess
import time

from operaciones.comun import (
    argumentos_psql,
    comando_en,
    compose,
    docker,
    esperar,
    id_contenedor,
    lineas_que_coinciden,
    psql,
    requerir_servicio,
    titulo,
)

NODO = "pg-sur"
COLUMNAS = (
    "(region, cliente_id, sucursal_origen_id, sucursal_destino_id, peso_kg, distancia_km, estado)"
)
PATRON_LOG = r"not properly shut down|redo starts|redo done|checkpoint complete|ready to accept"


def _insertar_envio(cliente: int) -> str:
    return f"INSERT INTO envios_sur {COLUMNAS} VALUES ('sur', {cliente}, 11, 12, 1, 1, 'pendiente')"


def ejecutar() -> None:
    requerir_servicio(NODO)

    titulo("1. Estado previo: checkpoint reciente")
    psql(
        NODO,
        "CHECKPOINT",
        "SELECT pg_current_wal_lsn() AS lsn_actual",
        "SELECT redo_lsn, checkpoint_lsn FROM pg_control_checkpoint()",
    )

    titulo("2. Dos transacciones: una confirmada (REDO) y una abierta (UNDO)")
    psql(NODO, _insertar_envio(1), _insertar_envio(2), silencioso=True)
    psql(
        NODO, "UPDATE envios_sur SET distancia_km = 111.1 WHERE cliente_id = 1 AND distancia_km = 1"
    )
    abierta = subprocess.Popen(
        comando_en(
            NODO,
            *argumentos_psql(
                "-c",
                "BEGIN; UPDATE envios_sur SET distancia_km = 222.2 "
                "WHERE cliente_id = 2 AND distancia_km = 1; SELECT pg_sleep(120);",
            ),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    print("Transacción abierta sin COMMIT en segundo plano.")

    titulo("3. Corte abrupto (SIGKILL: sin checkpoint de cierre)")
    docker("kill", "-s", "KILL", id_contenedor(NODO), capturar=True)
    abierta.kill()
    abierta.wait()
    compose("start", NODO, capturar=True)
    esperar(f"{NODO} disponible", lambda: psql(NODO, "SELECT 1", capturar=True).returncode == 0)

    titulo("4. Qué hizo el gestor de recuperación (log del servidor)")
    registro = compose("logs", "--no-log-prefix", "--since", "2m", NODO, capturar=True).stdout
    print("\n".join(lineas_que_coinciden(registro, PATRON_LOG)[-6:]))

    titulo("5. Resultado")
    psql(
        NODO,
        "SELECT cliente_id, distancia_km FROM envios_sur "
        "WHERE cliente_id IN (1, 2) AND distancia_km IN (1, 111.1, 222.2) ORDER BY cliente_id",
    )
    print(
        "cliente 1 -> 111.1 (COMMIT rehecho desde el WAL); cliente 2 -> 1 (sin COMMIT, descartado)"
    )
    psql(
        NODO,
        "DELETE FROM envios_sur WHERE cliente_id IN (1, 2) AND distancia_km IN (1, 111.1)",
        silencioso=True,
    )
