import uuid
from datetime import UTC, datetime

import pytest

from logistica import etl, mineria, tracking
from logistica.conexiones import conectar_pg, sesion_cassandra


def contar_dw() -> dict[str, int]:
    with conectar_pg("dw") as dw:
        return {
            tabla: dw.execute(f"SELECT count(*) AS n FROM {tabla}").fetchone()["n"]
            for tabla in ("hechos_entregas", "hechos_incidentes", "dim_tiempo", "dim_geografia")
        }


def test_etl_es_idempotente(datos_sembrados):
    etl.ejecutar_etl()
    primera = contar_dw()
    etl.ejecutar_etl()
    assert contar_dw() == primera
    assert primera["hechos_entregas"] > 0 and primera["hechos_incidentes"] > 0


def test_entregas_del_dw_coinciden_con_los_envios_entregados(datos_sembrados):
    etl.ejecutar_etl()
    with conectar_pg("centro") as central:
        origen = central.execute(
            "SELECT count(*) AS n FROM envios WHERE estado = 'entregado'"
        ).fetchone()["n"]
    assert contar_dw()["hechos_entregas"] == origen


def test_eta_supera_a_la_linea_base(datos_sembrados):
    etl.ejecutar_etl()
    resultado = mineria.entrenar_eta(mineria.cargar_entregas())
    assert resultado.mae_horas < resultado.mae_base_horas


def test_eta_rechaza_pocos_datos():
    import pandas as pd

    with pytest.raises(ValueError, match="insuficientes"):
        mineria.entrenar_eta(pd.DataFrame({"horas_entrega": [1.0]}))


def test_ciclo_de_vida_de_un_evento_de_tracking(datos_sembrados):
    paquete = uuid.uuid4()
    ts = tracking.registrar_evento(paquete, "ingreso_deposito", "sur", -38.9, -68.0)
    assert [e["tipo"] for e in tracking.historial_paquete(paquete)] == ["ingreso_deposito"]
    # Un INSERT sobre la misma clave (id_paquete, ts) es un upsert: modifica.
    tracking.registrar_evento(paquete, "en_transito", "sur", -38.9, -68.0, ts=ts)
    assert [e["tipo"] for e in tracking.historial_paquete(paquete)] == ["en_transito"]
    tracking.eliminar_evento(paquete, ts)
    assert tracking.historial_paquete(paquete) == []


def test_evento_con_tipo_invalido():
    with pytest.raises(ValueError, match="desconocido"):
        tracking.registrar_evento(uuid.uuid4(), "volando", "sur", 0, 0)


def test_incidentes_se_leen_por_region_y_mes(datos_sembrados):
    # Mes anterior al rango del ETL: no contamina el data warehouse.
    momento = datetime(2019, 6, 15, 12, tzinfo=UTC)
    id_incidente = tracking.registrar_incidente(
        "norte", momento, "robo", 30, -26.8, -65.2, sucursal_id=2
    )
    try:
        assert any(
            i["id_incidente"] == id_incidente
            for i in tracking.incidentes_del_mes("norte", "2019-06")
        )
    finally:
        sesion_cassandra().execute(
            "DELETE FROM tracking.incidentes_por_region "
            "WHERE region = 'norte' AND anio_mes = '2019-06' AND ts = %s AND id_incidente = %s",
            (momento, id_incidente),
        )
