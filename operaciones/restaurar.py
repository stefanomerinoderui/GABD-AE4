"""Restauración a un punto en el tiempo (PITR) en una instancia aparte (pg-restore).

No toca el clúster en producción. Pasos: último backup completo + incrementales posteriores
-> pg_combinebackup -> reproducir el WAL archivado hasta el instante pedido. Mide el tiempo
total (RTO).
"""

import re
import shlex
import time

from operaciones.backups import RAIZ_BACKUPS, backups_de_postgres
from operaciones.comun import (
    PROYECTO,
    OperacionError,
    compose,
    consulta,
    docker,
    esperar_valor,
    psql,
    servicio_primario,
    titulo,
)

SERVICIO = "pg-restore"
INSTANTE = re.compile(r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d(:?\d\d)?|Z)?$")

COMBINAR = """
set -euo pipefail
rm -rf "$PGDATA" && mkdir -p "$PGDATA" && chown postgres:postgres "$PGDATA" && chmod 700 "$PGDATA"
cd / && gosu postgres pg_combinebackup {cadena} --output="$PGDATA"
printf '%s\\n' {ajustes} | gosu postgres tee -a "$PGDATA/postgresql.auto.conf" > /dev/null
gosu postgres touch "$PGDATA/recovery.signal"
"""


def cadena_de_restauracion(nombres: list[str]) -> list[str]:
    """Último backup completo y los incrementales posteriores, en orden de aplicación."""
    validos = backups_de_postgres(nombres)
    completos = [i for i, nombre in enumerate(validos) if nombre.endswith("_completo")]
    if not completos:
        raise OperacionError("No hay ningún backup completo: ejecute 'backup' primero.")
    return validos[completos[-1] :]


def ajustes_de_recuperacion(instante: str | None) -> list[str]:
    if instante is not None and not INSTANTE.match(instante):
        raise OperacionError(
            f"Instante no válido: {instante!r}. Formato: 'AAAA-MM-DD HH:MM:SS+00'."
        )
    objetivo = (
        f"recovery_target_time = '{instante}'" if instante else "recovery_target = 'immediate'"
    )
    return [
        "restore_command = 'cp /backups/centro/wal/%f %p'",
        "recovery_target_action = 'promote'",
        objetivo,
        # Instancia de verificación: sin requisitos de réplica.
        "synchronous_standby_names = ''",
        "synchronized_standby_slots = ''",
    ]


def _en_pg_restore(*comando: str, capturar: bool = False):
    return compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--entrypoint",
        comando[0],
        SERVICIO,
        *comando[1:],
        capturar=capturar,
    )


def restaurar(instante: str | None = None) -> None:
    ajustes = ajustes_de_recuperacion(instante)
    inicio = time.monotonic()

    # Los segmentos de WAL se archivan al llenarse o cada 15 min: se fuerza el cierre del
    # actual para que la restauración vea todo lo confirmado hasta ahora.
    try:
        primario = servicio_primario()
        consulta(primario, "SELECT pg_switch_wal()")
        time.sleep(2)
    except OperacionError:
        print("Aviso: no hay primario en ejecución; se restaura solo lo ya archivado.")

    nombres = _en_pg_restore("ls", "-1", RAIZ_BACKUPS, capturar=True).stdout.split()
    cadena = cadena_de_restauracion(nombres)

    titulo("1. Combinar la cadena de backups, configurar la recuperación y arrancar")
    print("Cadena:", *cadena, sep="\n  ")
    rutas = " ".join(shlex.quote(f"{RAIZ_BACKUPS}/{nombre}") for nombre in cadena)
    guion = COMBINAR.format(cadena=rutas, ajustes=" ".join(shlex.quote(a) for a in ajustes))
    _en_pg_restore("bash", "-c", guion)
    compose("--profile", "restore", "up", "-d", "--wait", SERVICIO)

    titulo("2. Instancia restaurada")
    esperar_valor(SERVICIO, "SELECT pg_is_in_recovery()", "f")
    psql(
        SERVICIO,
        "SELECT (SELECT count(*) FROM clientes_operativo) AS clientes, "
        "(SELECT count(*) FROM facturas) AS facturas, "
        "(SELECT max(emitida_en) FROM facturas) AS ultima_factura",
    )
    print(f"\nRTO medido: {time.monotonic() - inicio:.0f} s (objetivo: 7200 s)")
    print("Elimine la instancia de prueba con: python tareas.py restore-limpiar")


def limpiar() -> None:
    compose("--profile", "restore", "rm", "-sf", SERVICIO)
    docker("volume", "rm", "-f", f"{PROYECTO}_pg-restore-data")
