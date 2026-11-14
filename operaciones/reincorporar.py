"""Reincorpora al antiguo primario (pg-centro) como standby síncrono del nuevo primario.

pg_rewind devuelve al antiguo primario a un punto común con el nuevo, descartando lo que
pudiera haber escrito solo en él, sin copiar toda la base.
"""

from operaciones.comun import (
    OperacionError,
    compose,
    consulta,
    esperar_valor,
    psql,
    requerir_servicio,
    titulo,
)

ANTIGUO = "pg-centro"
NUEVO = "pg-centro-replica"

# Se ejecuta DENTRO del contenedor (Linux), montando el volumen del antiguo primario.
REWIND_Y_STANDBY = """
set -euo pipefail
cd /
gosu postgres env PGPASSWORD="$POSTGRES_PASSWORD" pg_rewind \\
    --target-pgdata="$PGDATA" \\
    --source-server="host=pg-centro-replica port=5432 user=$POSTGRES_USER dbname=$POSTGRES_DB" \\
    --progress
gosu postgres touch "$PGDATA/standby.signal"
gosu postgres configurar_standby pg-centro-replica pg_centro
"""


def ejecutar() -> None:
    requerir_servicio(NUEVO)
    if consulta(NUEVO, "SELECT pg_is_in_recovery()") != "f":
        raise OperacionError(f"{NUEVO} no es primario: no hay nada que reincorporar.")
    compose("stop", ANTIGUO)

    titulo("1. Slot de replicación para el nuevo standby")
    psql(
        NUEVO,
        "SELECT pg_create_physical_replication_slot('standby_slot') "
        "WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name = 'standby_slot')",
        check=False,
    )

    titulo("2. pg_rewind y configuración como standby")
    compose(
        "run", "--rm", "--no-deps", "-T", "--entrypoint", "bash", ANTIGUO, "-c", REWIND_Y_STANDBY
    )

    titulo("3. Arranque como standby")
    compose("up", "-d", "--wait", ANTIGUO)
    esperar_valor(
        NUEVO,
        "SELECT count(*) FROM pg_stat_replication WHERE application_name = 'pg_centro'",
        "1",
    )

    titulo("4. Quórum restablecido")
    psql(
        NUEVO,
        "ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (pg_centro, pg_centro_replica)'",
        "SELECT pg_reload_conf()",
        silencioso=True,
    )
    psql(
        NUEVO,
        "DELETE FROM facturas WHERE monto = 0.01",
        "SELECT application_name, state, sync_state FROM pg_stat_replication",
    )
    print("Roles invertidos: pg-centro-replica es el primario y pg-centro su standby.")
