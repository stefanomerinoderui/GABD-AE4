"""Fixtures de integración: requieren el clúster levantado (`python tareas.py up`).

Ejecutar dentro del contenedor jupyter (`python tareas.py test`), que ve los nodos por
nombre. `test_operaciones.py` es unitario y corre también en el host, sin clúster.
"""

import time
import uuid

import pytest

from logistica import abm, semilla
from logistica.conexiones import conectar_pg, sesion_cassandra


def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.name != "test_operaciones.py":
            item.add_marker(pytest.mark.integracion)
            item.add_marker(pytest.mark.usefixtures("cluster_disponible"))


@pytest.fixture(scope="session")
def cluster_disponible():
    try:
        for nodo in ("centro", "norte", "sur", "dw"):
            conectar_pg(nodo).close()
        sesion_cassandra()
    except Exception as error:  # noqa: BLE001 - cualquier fallo significa "sin clúster"
        pytest.skip(f"Clúster no disponible: {error}")


@pytest.fixture(scope="session")
def datos_sembrados(cluster_disponible):
    """Garantiza datos de ejemplo; si el clúster está vacío carga un conjunto chico."""
    with conectar_pg("centro") as conexion:
        hay = conexion.execute("SELECT count(*) AS n FROM clientes_operativo").fetchone()["n"]
    if not hay:
        semilla.sembrar(
            semilla.Parametros(
                clientes=60,
                envios=400,
                incidentes=200,
                envios_con_tracking=40,
                camiones_con_telemetria=3,
            )
        )


def esperar(condicion, timeout_s: float = 20):
    """Reintenta `condicion()` hasta que sea verdadera (efectos de replicación asíncrona)."""
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        resultado = condicion()
        if resultado:
            return resultado
        time.sleep(0.3)
    raise AssertionError("La condición no se cumplió a tiempo")


@pytest.fixture
def cliente_id():
    """Cliente de prueba, ya replicado a las sucursales; se da de baja al terminar."""
    identificador = abm.alta_cliente(
        nombre="Cliente de prueba",
        email=f"prueba-{uuid.uuid4()}@ejemplo.com.ar",
        direccion="Calle Falsa 123",
        ciudad="Salta",
        provincia="Salta",
        region="norte",
        token_tarjeta="tok_prueba",
        ultimos4="4242",
        limite_credito=100000,
        scoring=700,
    )
    esperar(lambda: abm.obtener_cliente(identificador, "norte"))
    yield identificador
    with conectar_pg("centro") as conexion:
        conexion.execute(
            "DELETE FROM pagos WHERE factura_id IN (SELECT id FROM facturas WHERE cliente_id = %s)",
            (identificador,),
        )
        conexion.execute("DELETE FROM facturas WHERE cliente_id = %s", (identificador,))
        conexion.execute("DELETE FROM envios WHERE cliente_id = %s", (identificador,))
        conexion.execute("DELETE FROM clientes_operativo WHERE id = %s", (identificador,))
