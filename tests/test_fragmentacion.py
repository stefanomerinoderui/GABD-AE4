import psycopg
import pytest

from logistica.conexiones import conectar_pg

COLUMNAS = "(region, cliente_id, sucursal_origen_id, sucursal_destino_id, peso_kg, distancia_km)"


def contar(nodo: str, tabla: str) -> int:
    with conectar_pg(nodo) as conexion:
        return conexion.execute(f"SELECT count(*) AS n FROM {tabla}").fetchone()["n"]


def test_reconstruccion_la_tabla_global_es_la_union_de_los_fragmentos(datos_sembrados):
    total = contar("centro", "envios")
    fragmentos = (
        contar("centro", "envios_centro")
        + contar("norte", "envios_norte")
        + contar("sur", "envios_sur")
    )
    assert total == fragmentos > 0


def test_disyuncion_cada_fragmento_solo_tiene_su_region(datos_sembrados):
    for nodo, tabla in (("norte", "envios_norte"), ("sur", "envios_sur")):
        with conectar_pg(nodo) as conexion:
            ajenas = conexion.execute(
                f"SELECT count(*) AS n FROM {tabla} WHERE region <> %s", (nodo,)
            ).fetchone()["n"]
        assert ajenas == 0


def test_disyuncion_el_nodo_rechaza_filas_de_otra_region():
    with conectar_pg("norte") as conexion, pytest.raises(psycopg.errors.CheckViolation):
        conexion.execute(f"INSERT INTO envios_norte {COLUMNAS} VALUES ('sur', 1, 1, 2, 1, 1)")


def test_completitud_toda_region_valida_tiene_fragmento_y_las_invalidas_se_rechazan():
    with conectar_pg("centro") as conexion, pytest.raises(psycopg.errors.IntegrityError):
        conexion.execute(f"INSERT INTO envios {COLUMNAS} VALUES ('oeste', 1, 1, 2, 1, 1)")


def test_insercion_por_la_tabla_global_llega_al_nodo_correspondiente(datos_sembrados):
    with conectar_pg("centro") as conexion:
        cliente = conexion.execute("SELECT id FROM clientes_operativo LIMIT 1").fetchone()["id"]
        envio = conexion.execute(
            f"INSERT INTO envios {COLUMNAS} VALUES ('sur', %s, 11, 12, 1, 1) RETURNING id",
            (cliente,),
        ).fetchone()["id"]
    try:
        with conectar_pg("sur") as sur:
            assert sur.execute("SELECT 1 FROM envios_sur WHERE id = %s", (envio,)).fetchone()
        with conectar_pg("norte") as norte:
            assert not norte.execute(
                "SELECT 1 FROM envios_norte WHERE id = %s", (envio,)
            ).fetchone()
    finally:
        with conectar_pg("sur") as sur:
            sur.execute("DELETE FROM envios_sur WHERE id = %s", (envio,))


def test_fragmentacion_vertical_los_datos_sensibles_solo_existen_en_central():
    with conectar_pg("centro") as conexion:
        conexion.execute("SELECT token_tarjeta FROM clientes_sensible LIMIT 1")
    for nodo in ("norte", "sur"):
        with conectar_pg(nodo) as conexion, pytest.raises(psycopg.errors.UndefinedTable):
            conexion.execute("SELECT * FROM clientes_sensible")


def test_vista_clientes_reconstruye_los_dos_fragmentos(datos_sembrados):
    assert contar("centro", "clientes") == contar("centro", "clientes_operativo")


def test_replicacion_sincrona_hacia_el_standby():
    with conectar_pg("centro") as conexion:
        estado = conexion.execute(
            "SELECT sync_state FROM pg_stat_replication WHERE application_name LIKE 'pg_centro%'"
        ).fetchall()
    assert [f["sync_state"] for f in estado] and all(
        f["sync_state"] in ("sync", "quorum") for f in estado
    )


def test_hechos_del_dw_estan_particionados_por_rango_con_poda(datos_sembrados):
    with conectar_pg("dw") as conexion:
        particiones = {
            f["relname"]
            for f in conexion.execute(
                """
                SELECT c.relname FROM pg_inherits i
                JOIN pg_class c ON c.oid = i.inhrelid
                WHERE i.inhparent = 'hechos_entregas'::regclass
                """
            )
        }
        plan = "\n".join(
            f["QUERY PLAN"]
            for f in conexion.execute(
                "EXPLAIN SELECT * FROM hechos_entregas WHERE tiempo_id BETWEEN 20260101 AND 20261231"
            )
        )
    assert {"hechos_entregas_2025", "hechos_entregas_2026", "hechos_entregas_otros"} <= particiones
    assert "hechos_entregas_2026" in plan
    assert "hechos_entregas_2025" not in plan
