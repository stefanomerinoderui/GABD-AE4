import uuid

import pytest
from conftest import esperar

from logistica import abm
from logistica.conexiones import conectar_pg

ENVIO_NORTE = {
    "region": "norte",
    "sucursal_origen_id": 1,
    "sucursal_destino_id": 2,
    "peso_kg": 5,
    "distancia_km": 300,
}


def contar_envios_norte(cliente_id: int) -> int:
    with conectar_pg("norte") as conexion:
        return conexion.execute(
            "SELECT count(*) AS n FROM envios_norte WHERE cliente_id = %s", (cliente_id,)
        ).fetchone()["n"]


def test_alta_cliente_escribe_ambos_fragmentos_verticales(cliente_id):
    completo = abm.obtener_cliente(cliente_id, "centro")
    assert completo["ultimos4"] == "4242"
    assert completo["nombre"] == "Cliente de prueba"


def test_cliente_replicado_a_sucursal_sin_datos_sensibles(cliente_id):
    en_norte = abm.obtener_cliente(cliente_id, "norte")
    assert en_norte["nombre"] == "Cliente de prueba"
    assert "token_tarjeta" not in en_norte and "scoring" not in en_norte


def test_modificar_cliente_enruta_cada_campo_a_su_fragmento(cliente_id):
    abm.modificar_cliente(cliente_id, direccion="Otra 456", scoring=800)
    completo = abm.obtener_cliente(cliente_id)
    assert (completo["direccion"], completo["scoring"]) == ("Otra 456", 800)
    esperar(lambda: abm.obtener_cliente(cliente_id, "norte")["direccion"] == "Otra 456")


def test_modificar_cliente_rechaza_campos_desconocidos(cliente_id):
    with pytest.raises(abm.ValidacionError):
        abm.modificar_cliente(cliente_id, id=999)


def test_modificar_cliente_inexistente(cliente_id):
    with pytest.raises(abm.ValidacionError):
        abm.modificar_cliente(-1, nombre="x")


def test_baja_cliente_es_logica_y_borra_datos_sensibles(cliente_id):
    abm.baja_cliente(cliente_id)
    completo = abm.obtener_cliente(cliente_id)
    assert completo["activo"] is False
    assert completo["token_tarjeta"] is None
    esperar(lambda: abm.obtener_cliente(cliente_id, "norte")["activo"] is False)
    with pytest.raises(abm.ValidacionError, match="dado de baja"):
        abm.alta_envio(cliente_id=cliente_id, **ENVIO_NORTE)


def test_alta_envio_queda_en_el_fragmento_de_su_region(cliente_id):
    envio_id = abm.alta_envio(cliente_id=cliente_id, **ENVIO_NORTE)
    assert abm.obtener_envio("norte", envio_id)["estado"] == "pendiente"
    assert abm.obtener_envio("sur", envio_id) is None


def test_alta_envio_valida_que_el_origen_sea_de_la_region(cliente_id):
    datos = {**ENVIO_NORTE, "sucursal_origen_id": 11}  # sucursal del sur
    with pytest.raises(abm.ValidacionError, match="no pertenece"):
        abm.alta_envio(cliente_id=cliente_id, **datos)


def test_modificar_envio(cliente_id):
    envio_id = abm.alta_envio(cliente_id=cliente_id, **ENVIO_NORTE)
    abm.modificar_envio("norte", envio_id, estado="en_transito", vehiculo_id=1)
    envio = abm.obtener_envio("norte", envio_id)
    assert (envio["estado"], envio["vehiculo_id"]) == ("en_transito", 1)
    with pytest.raises(abm.ValidacionError):
        abm.modificar_envio("norte", envio_id, region="sur")


def test_alta_facturada_confirma_en_los_dos_nodos(cliente_id):
    envio_id, factura_id = abm.alta_envio_facturado(
        cliente_id=cliente_id, monto=1500, **ENVIO_NORTE
    )
    assert abm.obtener_envio("norte", envio_id) is not None
    assert abm.obtener_factura_de_envio(envio_id)["id"] == factura_id
    assert abm.transacciones_en_duda("norte") == []


def test_2pc_revierte_el_envio_si_falla_la_factura(cliente_id):
    # monto negativo viola el CHECK de facturas en pg-centro, DESPUÉS de haber
    # insertado el envío en pg-norte: el rollback debe deshacer ambos.
    with pytest.raises(Exception, match="check|monto"):
        abm.alta_envio_facturado(cliente_id=cliente_id, monto=-1, **ENVIO_NORTE)
    assert contar_envios_norte(cliente_id) == 0
    assert abm.transacciones_en_duda("norte") == []
    assert abm.transacciones_en_duda("centro") == []


def test_baja_envio_anula_la_factura(cliente_id):
    envio_id, _ = abm.alta_envio_facturado(cliente_id=cliente_id, monto=900, **ENVIO_NORTE)
    abm.baja_envio("norte", envio_id)
    assert abm.obtener_envio("norte", envio_id) is None
    assert abm.obtener_factura_de_envio(envio_id)["estado"] == "anulada"


def test_baja_envio_inexistente_no_deja_transacciones_colgadas():
    with pytest.raises(abm.ValidacionError):
        abm.baja_envio("norte", uuid.uuid4())
    assert abm.transacciones_en_duda("norte") == []


def test_pago_marca_la_factura_y_no_se_repite(cliente_id):
    _, factura_id = abm.alta_envio_facturado(cliente_id=cliente_id, monto=700, **ENVIO_NORTE)
    abm.registrar_pago(factura_id, 700, "transferencia")
    with pytest.raises(abm.ValidacionError, match="pagada"):
        abm.registrar_pago(factura_id, 700, "transferencia")
