"""Partición de red: aísla a las sucursales del Norte (pg-norte y cassandra-norte).

  Cassandra (AP)   el nodo aislado sigue aceptando escrituras locales (ONE)
  PostgreSQL       la sucursal sigue despachando (autonomía local), pero Central no puede
                   leer ese fragmento ni facturar con él (consistencia sobre disponibilidad)
Al reconectar, el Norte converge solo. La reconexión está en un `finally`: ocurre también
si el script se interrumpe (Ctrl+C) o falla a mitad de camino.
"""

import re

from operaciones.comun import (
    RED,
    consulta,
    cql,
    docker,
    en_contenedor,
    esperar,
    id_contenedor,
    lineas_que_coinciden,
    nodos_cassandra_arriba,
    psql,
    requerir_servicio,
    titulo,
)

PAQUETE = "00000000-0000-4000-8000-0000000000be"


def _reconectar(id_pg: str, id_cassandra: str) -> None:
    # Las IP y alias deben coincidir con compose.yaml: otros nodos resuelven por nombre.
    docker(
        "network",
        "connect",
        "--alias",
        "pg-norte",
        "--alias",
        "norte",
        RED,
        id_pg,
        check=False,
        capturar=True,
    )
    docker(
        "network", "connect", "--ip", "10.77.0.22", "--alias", "cassandra-norte",
        RED, id_cassandra, check=False, capturar=True,
    )  # fmt: skip


def ejecutar() -> None:
    requerir_servicio("pg-norte")
    requerir_servicio("cassandra-norte")
    id_pg = id_contenedor("pg-norte")
    id_cassandra = id_contenedor("cassandra-norte")
    aislado = False
    try:
        titulo("1. Aislamiento del Norte")
        docker("network", "disconnect", RED, id_pg)
        docker("network", "disconnect", RED, id_cassandra)
        aislado = True
        print("pg-norte y cassandra-norte sin conectividad con el resto.")

        titulo("2. PostgreSQL: el depósito del Norte registra un envío (autonomía local)")
        envio = consulta(
            "pg-norte",
            "INSERT INTO envios_norte (region, cliente_id, sucursal_origen_id, "
            "sucursal_destino_id, peso_kg, distancia_km) "
            "SELECT 'norte', min(id), 1, 2, 2, 300 FROM clientes_operativo WHERE region = 'norte' "
            "RETURNING id",
        ).splitlines()[0]
        print(f"Envío {envio} registrado en pg-norte sin conexión con Central.")

        titulo(
            "3. PostgreSQL: Central no puede consultar la tabla global (consistencia > disponibilidad)"
        )
        resultado = psql("pg-centro", "SELECT count(*) FROM envios", capturar=True, check=False)
        errores = lineas_que_coinciden(resultado.stdout, "ERROR")
        print(errores[0] if errores else "(la consulta no falló)")

        titulo("4. Cassandra: el nodo aislado sigue aceptando escrituras con ONE")
        cql(
            "cassandra-norte",
            "CONSISTENCY ONE;\n"
            "INSERT INTO tracking.eventos_por_paquete (id_paquete, ts, tipo, region, lat, lon) "
            f"VALUES ({PAQUETE}, '2026-01-02 09:00:00+0000', 'ingreso_deposito', 'norte', -24.78, -65.41);\n"
            f"SELECT tipo FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};",
        )

        titulo("5. Cassandra: desde Central el evento todavía no existe (consistencia eventual)")
        vistos = cql(
            "cassandra-centro",
            "CONSISTENCY ONE;\n"
            f"SELECT count(*) AS eventos_vistos FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};",
            capturar=True,
        ).stdout
        cuenta = [m.group(1) for m in re.finditer(r"^\s+(\d+)\s*$", vistos, re.MULTILINE)]
        print("eventos visibles desde Central:", cuenta[0] if cuenta else "?")
    finally:
        if aislado:
            titulo("6. Reconexión")
            _reconectar(id_pg, id_cassandra)

    esperar("anillo completo", lambda: nodos_cassandra_arriba("cassandra-centro") == 3)
    en_contenedor("cassandra-norte", "nodetool", "repair", "tracking", capturar=True)

    titulo("7. Tras la reparación, Central ve el evento (leyendo con ALL)")
    cql(
        "cassandra-centro",
        "CONSISTENCY ALL;\n"
        f"SELECT tipo FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};\n"
        f"DELETE FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};",
    )
    esperar(
        "pg-norte alcanzable desde Central",
        lambda: psql("pg-centro", "SELECT count(*) FROM envios", capturar=True).returncode == 0,
    )
    psql("pg-centro", f"SELECT count(*) AS envios_globales FROM envios WHERE id = '{envio}'")
    psql("pg-norte", f"DELETE FROM envios_norte WHERE id = '{envio}'", silencioso=True)
