"""Caída de un nodo de Cassandra: disponibilidad (AP) y convergencia eventual.

Con RF = 3 y un nodo caído:
  ONE / QUORUM  siguen funcionando (basta 1 o 2 réplicas vivas)
  ALL           falla (exige las 3)
Al volver el nodo, lo que se perdió llega por hinted handoff y `nodetool repair` lo garantiza.
"""

from operaciones.comun import (
    compose,
    cql,
    en_contenedor,
    esperar,
    estado_nodos_cassandra,
    lineas_que_coinciden,
    nodos_cassandra_arriba,
    requerir_servicio,
    titulo,
)

PAQUETE = "00000000-0000-4000-8000-0000000000ca"
INSERT = (
    "INSERT INTO tracking.eventos_por_paquete (id_paquete, ts, tipo, region, lat, lon) "
    "VALUES ({paquete}, '{ts}', '{tipo}', 'sur', {lat}, {lon});"
)


def _mostrar_estado(servicio: str) -> None:
    salida = en_contenedor(servicio, "nodetool", "status", capturar=True).stdout
    print("\n".join(estado_nodos_cassandra(salida)))


def ejecutar(nodo: str = "cassandra-sur") -> None:
    vivo = "cassandra-norte" if nodo == "cassandra-centro" else "cassandra-centro"
    requerir_servicio(nodo)

    titulo("1. Anillo completo")
    _mostrar_estado(vivo)

    titulo(f"2. Caída de {nodo}")
    compose("stop", nodo)
    esperar(
        "nodo marcado como caído",
        lambda: nodos_cassandra_arriba(vivo) == 2,
    )
    _mostrar_estado(vivo)

    titulo("3. Escritura con ONE y QUORUM: disponible")
    cql(
        vivo,
        "CONSISTENCY ONE;\n"
        + INSERT.format(
            paquete=PAQUETE, ts="2026-01-01 10:00:00+0000", tipo="en_transito", lat=-38.9, lon=-68.0
        )
        + "\nCONSISTENCY QUORUM;\n"
        + INSERT.format(
            paquete=PAQUETE, ts="2026-01-01 11:00:00+0000", tipo="en_transito", lat=-38.8, lon=-68.1
        ),
    )
    print("Escrituras aceptadas con un nodo caído.")

    titulo("4. Escritura con ALL: no disponible")
    rechazo = cql(
        vivo,
        "CONSISTENCY ALL;\n"
        + INSERT.format(
            paquete=PAQUETE, ts="2026-01-01 12:00:00+0000", tipo="entregado", lat=-38.7, lon=-68.2
        ),
        capturar=True,
        check=False,
    )
    errores = lineas_que_coinciden(rechazo.stdout, r"Unavailable|NoHostAvailable|Cannot achieve")
    print(errores[0] if errores else "(la escritura con ALL no falló)")

    titulo("5. Regreso del nodo y reparación")
    compose("start", nodo)
    esperar(
        f"{nodo} sano",
        lambda: cql(nodo, "SELECT now() FROM system.local", capturar=True).returncode == 0,
    )
    esperar("anillo completo", lambda: nodos_cassandra_arriba(vivo) == 3)
    en_contenedor(vivo, "nodetool", "repair", "tracking", capturar=True)

    titulo("6. Lectura con ALL desde el nodo recuperado: las 2 escrituras convergieron")
    cql(
        nodo,
        f"CONSISTENCY ALL;\nSELECT ts, tipo FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};",
    )
    cql(vivo, f"DELETE FROM tracking.eventos_por_paquete WHERE id_paquete = {PAQUETE};")
