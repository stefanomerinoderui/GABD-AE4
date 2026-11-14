"""Failover del primario de Central (pg-centro -> pg-centro-replica).

Muestra el comportamiento CP del subsistema relacional:
  * Con el primario caído no hay escrituras hasta promover al standby.
  * El standby síncrono tiene TODO lo confirmado: no se pierde ninguna transacción.
  * El nuevo primario exige un standby síncrono; mientras no lo tenga, los COMMIT
    quedan esperando (se sacrifica disponibilidad para no desfasar datos financieros).

Con `degradado=True` (decisión explícita de operaciones) se desactiva el requisito de
standby síncrono para volver a aceptar escrituras; riesgo: si el nuevo primario cae,
podrían perderse los últimos commits. Para volver a la normalidad: `reincorporar`.
"""

import subprocess
import time

from operaciones.comun import (
    argumentos_psql,
    comando_en,
    compose,
    consulta,
    esperar_valor,
    psql,
    requerir_servicio,
    titulo,
)

PRIMARIO = "pg-centro"
STANDBY = "pg-centro-replica"

FACTURA_DE_PRUEBA = """
    INSERT INTO facturas (envio_id, region_envio, cliente_id, monto)
    SELECT gen_random_uuid(), 'centro', min(id), {monto} FROM clientes_operativo"""


def _commit_bloqueado_por_quorum() -> None:
    """Lanza un INSERT que no puede confirmarse y muestra su espera en SyncRep.

    El INSERT queda confirmado localmente pero el cliente no recibe respuesta hasta
    que haya quórum; se observa en pg_stat_activity y luego se cancela el cliente.
    """
    cliente = subprocess.Popen(
        comando_en(STANDBY, *argumentos_psql("-c", FACTURA_DE_PRUEBA.format(monto="0.01"))),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(3)
        psql(
            STANDBY,
            "SELECT wait_event_type, wait_event, left(query, 40) AS consulta "
            "FROM pg_stat_activity WHERE wait_event = 'SyncRep'",
        )
    finally:
        cliente.kill()
        cliente.wait()


def ejecutar(degradado: bool = False) -> None:
    requerir_servicio(PRIMARIO)
    requerir_servicio(STANDBY)

    titulo("1. Estado inicial")
    psql(PRIMARIO, "SELECT application_name, state, sync_state FROM pg_stat_replication")

    titulo("2. Factura confirmada en el primario antes de la caída")
    print(
        "factura",
        consulta(
            PRIMARIO,
            FACTURA_DE_PRUEBA.format(monto="777.77") + " RETURNING id",
        ).splitlines()[0],
        "confirmada (monto 777.77)",
    )

    titulo("3. Caída del primario")
    compose("stop", PRIMARIO)

    titulo("4. Promoción del standby")
    psql(STANDBY, "SELECT pg_promote(wait => true)")
    esperar_valor(STANDBY, "SELECT pg_is_in_recovery()", "f")
    # El nuevo primario no tiene el slot físico del standby: los slots lógicos de las
    # sucursales no deben esperar por él.
    psql(
        STANDBY,
        "ALTER SYSTEM SET synchronized_standby_slots = ''",
        "SELECT pg_reload_conf()",
        silencioso=True,
    )
    print(f"{STANDBY} es ahora el primario.")

    titulo("5. Cero pérdida de datos: la factura confirmada sigue ahí")
    psql(STANDBY, "SELECT id, monto FROM facturas WHERE monto = 777.77")

    titulo("6. Sin standby síncrono, los COMMIT esperan (CP)")
    _commit_bloqueado_por_quorum()

    if degradado:
        titulo("7. Modo degradado: se desactiva el requisito de standby síncrono")
        psql(
            STANDBY,
            "ALTER SYSTEM SET synchronous_standby_names = ''",
            "SELECT pg_reload_conf()",
            silencioso=True,
        )
        psql(
            STANDBY,
            "DELETE FROM facturas WHERE monto = 0.01",
            "SELECT count(*) AS facturas FROM facturas",
        )
        print("Las escrituras vuelven a estar disponibles, sin respaldo síncrono.")
    else:
        titulo("7. Siguiente paso")
        print("Las escrituras siguen bloqueadas hasta recuperar el quórum.")
        print("Ejecute 'python tareas.py reincorporar' (recomendado) o repita con --degradado.")
