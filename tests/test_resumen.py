import pytest

from logistica import resumen
from logistica.conexiones import conectar_pg

DESGLOSE_DIRECTO = """
    SELECT region, count(*) AS n FROM envios GROUP BY region ORDER BY region
"""
DESGLOSE_VISTA = """
    SELECT region, sum(total_envios)::bigint AS n FROM resumen_envios_mensual
    GROUP BY region ORDER BY region
"""


def desglose(consulta: str) -> list[tuple]:
    with conectar_pg("centro") as conexion:
        return [(f["region"], f["n"]) for f in conexion.execute(consulta)]


@pytest.mark.parametrize(("poblada", "esperado"), [(False, "completo"), (True, "concurrente")])
def test_modo_de_refresco_concurrente_solo_si_esta_poblada(poblada, esperado):
    assert resumen.modo_de_refresco(poblada) == esperado


def test_sentencias_ignoran_comentarios_con_punto_y_coma():
    texto = "-- comentario; con punto y coma\nSELECT 1;\nSELECT 2;"
    assert resumen.sentencias_de(texto) == ["SELECT 1", "SELECT 2"]


def test_la_vista_tiene_el_indice_unico_que_exige_concurrently(datos_sembrados):
    resumen.refrescar()
    with conectar_pg("centro") as conexion:
        fila = conexion.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'resumen_envios_mensual_pk'"
        ).fetchone()
    assert fila is not None
    assert "UNIQUE" in fila["indexdef"]


def test_refresco_coincide_con_la_agregacion_directa(datos_sembrados):
    resultado = resumen.refrescar()
    assert resultado["modo"] == "concurrente"
    assert desglose(DESGLOSE_VISTA) == desglose(DESGLOSE_DIRECTO)


def test_el_refresco_concurrente_incorpora_envios_nuevos(datos_sembrados):
    resumen.refrescar()
    antes = sum(n for _, n in desglose(DESGLOSE_VISTA))
    with conectar_pg("centro") as conexion:
        id_nuevo = conexion.execute(
            """
            INSERT INTO envios_centro
                (region, cliente_id, sucursal_origen_id, sucursal_destino_id, peso_kg, distancia_km)
            VALUES ('centro', 1, 1, 1, 1, 1) RETURNING id
            """
        ).fetchone()["id"]
    try:
        assert resumen.refrescar()["modo"] == "concurrente"
        assert sum(n for _, n in desglose(DESGLOSE_VISTA)) == antes + 1
    finally:
        with conectar_pg("centro") as conexion:
            conexion.execute("DELETE FROM envios_centro WHERE id = %s", (id_nuevo,))
        resumen.refrescar()
