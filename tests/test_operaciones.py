"""Tests unitarios de la lógica pura de `operaciones` (no requieren el clúster)."""

import pytest
from operaciones import backups, restaurar
from operaciones.comun import OperacionError, cargar_env, estado_nodos_cassandra

NOMBRES = [
    "20260101T020000Z_completo",
    "20260101T030000Z_incremental",
    "20260108T020000Z_completo",
    "20260108T030000Z_incremental",
    "20260108T040000Z_incremental",
    "wal",
]


def test_ultimo_backup_ignora_entradas_ajenas():
    assert backups.ultimo_backup(NOMBRES) == "20260108T040000Z_incremental"


def test_ultimo_backup_sin_backups():
    assert backups.ultimo_backup(["wal"]) is None


def test_cadena_parte_del_ultimo_completo():
    assert restaurar.cadena_de_restauracion(NOMBRES) == [
        "20260108T020000Z_completo",
        "20260108T030000Z_incremental",
        "20260108T040000Z_incremental",
    ]


def test_cadena_exige_un_completo():
    with pytest.raises(OperacionError, match="completo"):
        restaurar.cadena_de_restauracion(["20260101T030000Z_incremental"])


def test_ajustes_sin_instante_recupera_el_final_del_backup():
    assert "recovery_target = 'immediate'" in restaurar.ajustes_de_recuperacion(None)


def test_ajustes_con_instante():
    ajustes = restaurar.ajustes_de_recuperacion("2026-11-14 21:58:16+00")
    assert "recovery_target_time = '2026-11-14 21:58:16+00'" in ajustes


@pytest.mark.parametrize("instante", ["ayer", "2026-11-14'; DROP TABLE x; --", "2026-11-14"])
def test_ajustes_rechaza_instantes_invalidos(instante):
    with pytest.raises(OperacionError, match="no válido"):
        restaurar.ajustes_de_recuperacion(instante)


def test_estado_de_nodos_de_cassandra():
    salida = (
        "Datacenter: logistica\n=====\nStatus=Up/Down\n"
        "--  Address     Load  Tokens  Owns  Host ID  Rack\n"
        "UN  10.77.0.21  100 KiB  16  100.0%  abc  centro\n"
        "DN  10.77.0.23  100 KiB  16  100.0%  def  sur\n"
    )
    estados = estado_nodos_cassandra(salida)
    assert [linea[:2] for linea in estados] == ["UN", "DN"]


def test_cargar_env_ignora_comentarios_y_comillas(tmp_path):
    ruta = tmp_path / ".env"
    ruta.write_text('# comentario\nA=1\n\nB = "dos"\nsin_igual\n', encoding="utf-8")
    assert cargar_env(ruta) == {"A": "1", "B": "dos"}


def test_cargar_env_inexistente(tmp_path):
    assert cargar_env(tmp_path / "no_existe") == {}
