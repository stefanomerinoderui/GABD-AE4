"""Datos sintéticos deterministas (semilla fija) para todo el sistema.

Se inyecta señal a propósito para que la analítica tenga algo que encontrar:

* El tiempo de entrega depende de distancia, tráfico y lluvia (regresión de ETA).
* Los incidentes se concentran alrededor de ``ZONAS_CRITICAS`` (clustering).
* La región sur mejora su tiempo de entrega entre 2025 y 2026 (comparación OLAP).
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from cassandra.concurrent import execute_concurrent_with_args

from logistica import config, tracking
from logistica.conexiones import conectar_pg, sesion_cassandra
from logistica.geo import haversine_km

log = logging.getLogger(__name__)

SEMILLA = 42
INICIO = datetime(2025, 1, 1, tzinfo=UTC)
CORTE = datetime(2026, 11, 1, tzinfo=UTC)  # "ahora" de los datos sintéticos
DIAS_DE_DATOS = (CORTE - INICIO).days + 2

# (lat, lon, desvío en grados, peso relativo) de las zonas con más incidentes.
ZONAS_CRITICAS = {
    "norte": [(-26.83, -65.20, 0.12, 3), (-27.45, -58.90, 0.10, 2)],
    "centro": [(-34.60, -58.45, 0.10, 4), (-32.95, -60.65, 0.08, 2)],
    "sur": [(-38.95, -68.05, 0.12, 2)],
}
TIPOS_INCIDENTE = ("demora_trafico", "falla_mecanica", "corte_ruta", "robo", "ruptura_cadena_frio")
PAGOS_MEDIOS = ("tarjeta", "transferencia", "efectivo")
TABLAS_CASSANDRA = ("eventos_por_paquete", "telemetria_por_camion", "incidentes_por_region")


@dataclass(frozen=True)
class Parametros:
    clientes: int = 300
    envios: int = 4000
    incidentes: int = 1500
    envios_con_tracking: int = 400
    camiones_con_telemetria: int = 10


def _uuid(rng: np.random.Generator) -> uuid.UUID:
    return uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | int(rng.integers(0, 2**63)), version=4)


def _catalogo() -> tuple[list[dict], list[dict]]:
    with conectar_pg("centro") as conexion:
        sucursales = conexion.execute("SELECT * FROM sucursales ORDER BY id").fetchall()
        vehiculos = conexion.execute("SELECT * FROM vehiculos ORDER BY id").fetchall()
    return sucursales, vehiculos


def limpiar() -> None:
    """Vacía todas las tablas de datos (el catálogo de sucursales y flota se conserva)."""
    for region in ("norte", "sur"):
        with conectar_pg(region) as conexion:
            conexion.execute(f"TRUNCATE {config.tabla_envios(region)}")
    with conectar_pg("centro") as conexion:
        conexion.execute("TRUNCATE envios_centro")
        conexion.execute("TRUNCATE pagos, facturas, clientes_sensible, clientes_operativo")
    sesion = sesion_cassandra()
    for tabla in TABLAS_CASSANDRA:
        sesion.execute(f"TRUNCATE {config.CASSANDRA_KEYSPACE}.{tabla}")


def _cargar_clientes(rng: np.random.Generator, sucursales: list[dict], n: int) -> list[dict]:
    regiones = rng.choice(config.REGIONES, size=n, p=[0.30, 0.45, 0.25])
    clientes = []
    for i in range(1, n + 1):
        sucursal = rng.choice([s for s in sucursales if s["region"] == regiones[i - 1]])
        clientes.append(
            {
                "id": i,
                "nombre": f"Cliente {i:04d}",
                "email": f"cliente{i:04d}@ejemplo.com.ar",
                "telefono": f"+54 9 11 {rng.integers(4000, 9999)}-{rng.integers(1000, 9999)}",
                "direccion": f"Calle {rng.integers(1, 3000)} {rng.integers(100, 9000)}",
                "ciudad": sucursal["ciudad"],
                "provincia": sucursal["provincia"],
                "region": sucursal["region"],
                "token": f"tok_{uuid.UUID(int=int(rng.integers(0, 2**62))).hex[:20]}",
                "ultimos4": f"{rng.integers(0, 10000):04d}",
                "limite": float(rng.choice([50000, 100000, 250000, 500000])),
                "scoring": int(np.clip(rng.normal(650, 120), 0, 1000)),
            }
        )
    with conectar_pg("centro") as conexion, conexion.cursor() as cur:
        cur.executemany(
            """INSERT INTO clientes_operativo
               (id, nombre, email, telefono, direccion, ciudad, provincia, region)
               VALUES (%(id)s, %(nombre)s, %(email)s, %(telefono)s, %(direccion)s,
                       %(ciudad)s, %(provincia)s, %(region)s)""",
            clientes,
        )
        cur.executemany(
            """INSERT INTO clientes_sensible
               (cliente_id, token_tarjeta, ultimos4, limite_credito, scoring)
               VALUES (%(id)s, %(token)s, %(ultimos4)s, %(limite)s, %(scoring)s)""",
            clientes,
        )
        # Los ids se fijaron a mano: se avanza la secuencia para los altas futuros.
        cur.execute("SELECT setval(pg_get_serial_sequence('clientes_operativo', 'id'), %s)", (n,))
    return clientes


def _generar_envios(
    rng: np.random.Generator,
    n: int,
    clientes: list[dict],
    sucursales: list[dict],
    vehiculos: list[dict],
) -> list[dict]:
    por_id = {s["id"]: s for s in sucursales}
    por_region = {r: [s for s in sucursales if s["region"] == r] for r in config.REGIONES}
    flota = {
        r: [v["id"] for v in vehiculos if por_id[v["sucursal_base_id"]]["region"] == r]
        for r in config.REGIONES
    }
    clientes_region = {r: [c for c in clientes if c["region"] == r] for r in config.REGIONES}

    envios = []
    for _ in range(n):
        region = str(rng.choice(config.REGIONES, p=[0.30, 0.45, 0.25]))
        origen = rng.choice(por_region[region])
        # 85 % de los envíos termina en la misma región (alcance regional).
        pool = por_region[region] if rng.random() < 0.85 else sucursales
        destino = rng.choice([s for s in pool if s["id"] != origen["id"]])
        km = float(
            haversine_km(origen["lat"], origen["lon"], destino["lat"], destino["lon"]) * 1.25
        )
        alta = INICIO + timedelta(seconds=float(rng.uniform(0, DIAS_DE_DATOS * 86400)))
        alta = alta.replace(hour=int(rng.integers(6, 21)))
        trafico = float(np.clip(rng.beta(2, 3), 0, 1))
        lluvia = float(min(rng.exponential(8), 60)) if rng.random() < 0.3 else 0.0
        # La región sur era más lenta en 2025; mejoró en 2026.
        factor = 1.15 if region == "sur" and alta.year == 2025 else 1.0
        horas = max(
            1.0,
            2 + km / 58 * (1 + 0.5 * trafico) * factor + 0.25 * lluvia + rng.normal(0, 1.0),
        )
        entrega = alta + timedelta(hours=horas)

        if rng.random() < 0.03:
            estado, entrega = "cancelado", None
        elif entrega <= CORTE:
            estado = "entregado"
        elif alta <= CORTE - timedelta(days=1):
            estado, entrega = "en_transito", None
        else:
            estado, entrega = "pendiente", None

        envios.append(
            {
                "id": _uuid(rng),
                "region": region,
                "cliente_id": rng.choice(clientes_region[region])["id"],
                "origen": origen,
                "destino": destino,
                "vehiculo_id": rng.choice(flota[region]) if estado != "pendiente" else None,
                "peso_kg": round(float(np.clip(rng.lognormal(2.5, 0.9), 0.1, 900)), 2),
                "distancia_km": round(km, 1),
                "lluvia_mm": round(lluvia, 1),
                "indice_trafico": round(trafico, 2),
                "estado": estado,
                "fecha_alta": alta,
                "fecha_entrega": entrega,
            }
        )
    return envios


def _cargar_envios_y_facturas(rng: np.random.Generator, envios: list[dict]) -> None:
    columnas = (
        "id, region, cliente_id, sucursal_origen_id, sucursal_destino_id, vehiculo_id, "
        "peso_kg, distancia_km, lluvia_mm, indice_trafico, estado, fecha_alta, fecha_entrega"
    )
    for region in config.REGIONES:
        propios = [e for e in envios if e["region"] == region]
        with (
            conectar_pg(region) as conexion,
            conexion.cursor() as cur,
            cur.copy(f"COPY {config.tabla_envios(region)} ({columnas}) FROM STDIN") as copy,
        ):
            for e in propios:
                copy.write_row(
                    (
                        e["id"],
                        e["region"],
                        e["cliente_id"],
                        e["origen"]["id"],
                        e["destino"]["id"],
                        e["vehiculo_id"],
                        e["peso_kg"],
                        e["distancia_km"],
                        e["lluvia_mm"],
                        e["indice_trafico"],
                        e["estado"],
                        e["fecha_alta"],
                        e["fecha_entrega"],
                    )
                )

    with conectar_pg("centro") as conexion, conexion.cursor() as cur:
        with cur.copy(
            "COPY facturas (envio_id, region_envio, cliente_id, monto, estado, emitida_en) "
            "FROM STDIN"
        ) as copy:
            for e in envios:
                monto = round(
                    450 + 9 * e["distancia_km"] + 1.8 * e["peso_kg"] + rng.normal(0, 40), 2
                )
                if e["estado"] == "cancelado":
                    estado = "anulada"
                elif e["estado"] == "entregado" and rng.random() < 0.85:
                    estado = "pagada"
                else:
                    estado = "emitida"
                copy.write_row(
                    (
                        e["id"],
                        e["region"],
                        e["cliente_id"],
                        max(monto, 100),
                        estado,
                        e["fecha_alta"],
                    )
                )
        cur.execute(
            """INSERT INTO pagos (factura_id, monto, medio, pagado_en)
               SELECT id, monto, (%s::text[])[1 + id %% 3], emitida_en + interval '2 days'
               FROM facturas WHERE estado = 'pagada'""",
            (list(PAGOS_MEDIOS),),
        )


def _cargar_tracking(
    rng: np.random.Generator, envios: list[dict], vehiculos: list[dict], p: Parametros
) -> None:
    sesion = sesion_cassandra()
    insertar_evento = sesion.prepare(tracking.INSERT_EVENTO)
    entregados = [e for e in envios if e["estado"] == "entregado"]
    muestra = rng.choice(
        len(entregados), size=min(p.envios_con_tracking, len(entregados)), replace=False
    )

    eventos = []
    for indice in muestra:
        e = entregados[indice]
        o, d = e["origen"], e["destino"]
        duracion = e["fecha_entrega"] - e["fecha_alta"]
        # (tipo, fracción del trayecto, sucursal de la que sale el evento)
        etapas = [
            ("ingreso_deposito", 0.0, o),
            ("en_transito", 0.3, None),
            ("en_transito", 0.65, None),
            ("en_reparto", 0.9, d),
            ("entregado", 1.0, d),
        ]
        for tipo, fraccion, sucursal in etapas:
            ts = e["fecha_alta"] + duracion * fraccion
            ts = ts.replace(microsecond=ts.microsecond // 1000 * 1000)
            lat = o["lat"] + (d["lat"] - o["lat"]) * fraccion
            lon = o["lon"] + (d["lon"] - o["lon"]) * fraccion
            eventos.append(
                (
                    e["id"],
                    ts,
                    tipo,
                    e["region"],
                    sucursal["id"] if sucursal else None,
                    lat,
                    lon,
                    None,
                )
            )
    execute_concurrent_with_args(sesion, insertar_evento, eventos, concurrency=64)

    insertar_telemetria = sesion.prepare(tracking.INSERT_TELEMETRIA)
    refrigerados = [v for v in vehiculos if v["tipo"] == "camion_refrigerado"]
    elegidos = refrigerados[: p.camiones_con_telemetria]
    lecturas = []
    for vehiculo in elegidos:
        dia = INICIO + timedelta(days=int(rng.integers(30, 600)))
        lat, lon = -34.6 + rng.normal(0, 0.5), -58.4 + rng.normal(0, 0.5)
        for minuto in range(0, 600, 10):  # 10 h de ruta, una lectura cada 10 min
            lat += rng.normal(0, 0.02)
            lon += rng.normal(0, 0.02)
            ts = dia.replace(hour=6) + timedelta(minutes=minuto)
            lecturas.append(
                (
                    vehiculo["id"],
                    ts.date(),
                    ts,
                    lat,
                    lon,
                    float(np.clip(rng.normal(70, 15), 0, 110)),
                    float(rng.normal(4.0, 0.8)),  # cadena de frío: ~4 °C
                )
            )
    execute_concurrent_with_args(sesion, insertar_telemetria, lecturas, concurrency=64)


def _cargar_incidentes(rng: np.random.Generator, sucursales: list[dict], n: int) -> None:
    zonas = [(region, *zona) for region, lista in ZONAS_CRITICAS.items() for zona in lista]
    pesos = np.array([z[4] for z in zonas], dtype=float)
    pesos /= pesos.sum()
    lats = np.array([s["lat"] for s in sucursales])
    lons = np.array([s["lon"] for s in sucursales])

    filas = []
    for _ in range(n):
        if rng.random() < 0.85:  # incidente en una zona crítica
            region, lat0, lon0, sigma, _peso = zonas[rng.choice(len(zonas), p=pesos)]
            lat, lon = rng.normal(lat0, sigma), rng.normal(lon0, sigma)
            demora = int(rng.lognormal(4.4, 0.5))
        else:  # incidente aislado en cualquier punto del país
            lat, lon = rng.uniform(-50, -22), rng.uniform(-72, -55)
            demora = int(rng.lognormal(3.4, 0.5))
            region = None
        cercana = int(np.argmin(haversine_km(lat, lon, lats, lons)))
        sucursal = sucursales[cercana]
        ts = INICIO + timedelta(seconds=float(rng.uniform(0, DIAS_DE_DATOS * 86400)))
        filas.append(
            (
                region or sucursal["region"],
                tracking.anio_mes(ts),
                ts.replace(microsecond=ts.microsecond // 1000 * 1000),
                _uuid(rng),
                str(rng.choice(TIPOS_INCIDENTE)),
                demora,
                int(rng.integers(1, 61)),
                sucursal["id"],
                float(lat),
                float(lon),
            )
        )
    sesion = sesion_cassandra()
    execute_concurrent_with_args(
        sesion, sesion.prepare(tracking.INSERT_INCIDENTE), filas, concurrency=64
    )


def esperar_replicacion(timeout_s: int = 60) -> None:
    """Espera a que los nodos regionales reciban el catálogo (replicación asíncrona)."""
    with conectar_pg("centro") as central:
        esperado = central.execute("SELECT count(*) AS n FROM clientes_operativo").fetchone()["n"]
    limite = time.monotonic() + timeout_s
    for region in ("norte", "sur"):
        while True:
            with conectar_pg(region) as conexion:
                actual = conexion.execute(
                    "SELECT count(*) AS n FROM clientes_operativo"
                ).fetchone()["n"]
            if actual == esperado:
                break
            if time.monotonic() > limite:
                raise TimeoutError(
                    f"{region} tiene {actual}/{esperado} clientes tras {timeout_s} s"
                )
            time.sleep(0.5)


def sembrar(parametros: Parametros = Parametros(), *, reiniciar: bool = False) -> dict[str, int]:
    """Carga el conjunto de datos completo. Con `reiniciar=True` vacía antes."""
    with conectar_pg("centro") as conexion:
        existentes = conexion.execute("SELECT count(*) AS n FROM clientes_operativo").fetchone()[
            "n"
        ]
    if existentes and not reiniciar:
        raise RuntimeError("Ya hay datos cargados. Use reiniciar=True para recrearlos.")
    if existentes:
        limpiar()

    rng = np.random.default_rng(SEMILLA)
    sucursales, vehiculos = _catalogo()
    log.info("Cargando clientes")
    clientes = _cargar_clientes(rng, sucursales, parametros.clientes)
    esperar_replicacion()
    log.info("Cargando envíos y facturas")
    envios = _generar_envios(rng, parametros.envios, clientes, sucursales, vehiculos)
    _cargar_envios_y_facturas(rng, envios)
    log.info("Cargando tracking en Cassandra")
    _cargar_tracking(rng, envios, vehiculos, parametros)
    _cargar_incidentes(rng, sucursales, parametros.incidentes)
    return {
        "clientes": len(clientes),
        "envios": len(envios),
        "incidentes": parametros.incidentes,
        "envios_con_tracking": parametros.envios_con_tracking,
    }
