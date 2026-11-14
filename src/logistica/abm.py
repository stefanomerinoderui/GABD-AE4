"""ABM (alta, baja y modificación) del subsistema relacional.

Cada operación se dirige al nodo dueño del dato:

* Clientes y facturación -> pg-centro (con réplica síncrona).
* Envíos -> el nodo de la región del envío, sin pasar por la sede Central,
  de modo que una sucursal sigue despachando aunque se corte el enlace.
* Operaciones que tocan dos nodos (envío + factura) -> two-phase commit.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress

import psycopg
from psycopg import sql

from logistica import config
from logistica.conexiones import conectar_pg

log = logging.getLogger(__name__)

CAMPOS_CLIENTE_OPERATIVO = frozenset(
    {"nombre", "email", "telefono", "direccion", "ciudad", "provincia", "region"}
)
CAMPOS_CLIENTE_SENSIBLE = frozenset({"token_tarjeta", "ultimos4", "limite_credito", "scoring"})
CAMPOS_ENVIO_MODIFICABLES = frozenset(
    {"estado", "vehiculo_id", "peso_kg", "fecha_entrega", "lluvia_mm", "indice_trafico"}
)


class ValidacionError(ValueError):
    """La operación viola una regla de negocio y no llegó a ejecutarse."""


# --------------------------------------------------------------------- utilidades


def _asignaciones(campos: dict) -> sql.Composed:
    """Arma `col1 = %(col1)s, col2 = %(col2)s` con identificadores escapados."""
    return sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(campo), sql.Placeholder(campo)) for campo in campos
    )


def _validar_campos(campos: dict, permitidos: frozenset[str], entidad: str) -> None:
    if not campos:
        raise ValidacionError(f"No se indicó ningún campo de {entidad} a modificar")
    desconocidos = set(campos) - permitidos
    if desconocidos:
        raise ValidacionError(f"Campos no modificables en {entidad}: {sorted(desconocidos)}")


@contextmanager
def transaccion_distribuida(*nodos: str) -> Iterator[list[psycopg.Connection]]:
    """Transacción atómica sobre varios nodos mediante two-phase commit.

    Fase 1 (votación): cada nodo ejecuta PREPARE TRANSACTION y persiste la
    transacción en su WAL; a partir de ahí promete poder confirmarla aunque
    se reinicie. Fase 2 (decisión): si todos votaron que sí, COMMIT PREPARED
    en cada uno; si alguno falló, ROLLBACK en todos.
    """
    id_global = f"lf-{uuid.uuid4()}"
    conexiones = [conectar_pg(nodo) for nodo in nodos]
    try:
        try:
            for rama, conexion in enumerate(conexiones):
                conexion.tpc_begin(conexion.xid(1, id_global, f"rama-{rama}"))
            yield conexiones
            for conexion in conexiones:
                conexion.tpc_prepare()
        except BaseException:
            for conexion in conexiones:
                # Una rama que no llegó a iniciarse no tiene nada que deshacer.
                with suppress(psycopg.Error):
                    conexion.tpc_rollback()
            raise

        # Todos los participantes votaron que sí: la decisión ya es COMMIT.
        # Si un nodo cae justo acá, su rama queda "en duda" en
        # pg_prepared_xacts y se resuelve con COMMIT PREPARED al volver.
        for conexion in conexiones:
            try:
                conexion.tpc_commit()
            except psycopg.Error:
                log.exception("Rama en duda de la transacción %s: requiere resolución", id_global)
                raise
    finally:
        for conexion in conexiones:
            conexion.close()


def transacciones_en_duda(nodo: str) -> list[dict]:
    """Transacciones preparadas pendientes de decisión en un nodo."""
    with conectar_pg(nodo) as conexion:
        return conexion.execute(
            "SELECT gid, prepared, owner FROM pg_prepared_xacts ORDER BY prepared"
        ).fetchall()


# ----------------------------------------------------------------------- clientes


def alta_cliente(
    *,
    nombre: str,
    email: str,
    direccion: str,
    ciudad: str,
    provincia: str,
    region: str,
    token_tarjeta: str,
    ultimos4: str,
    limite_credito: float,
    scoring: int,
    telefono: str | None = None,
) -> int:
    """Crea un cliente escribiendo sus dos fragmentos verticales en una transacción."""
    config.validar_region(region)
    with conectar_pg("centro") as conexion:
        fila = conexion.execute(
            """
            INSERT INTO clientes_operativo
                (nombre, email, telefono, direccion, ciudad, provincia, region)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (nombre, email, telefono, direccion, ciudad, provincia, region),
        ).fetchone()
        conexion.execute(
            """
            INSERT INTO clientes_sensible
                (cliente_id, token_tarjeta, ultimos4, limite_credito, scoring)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (fila["id"], token_tarjeta, ultimos4, limite_credito, scoring),
        )
    return fila["id"]


def modificar_cliente(cliente_id: int, /, **campos) -> None:
    """Actualiza un cliente; cada campo se enruta al fragmento que lo contiene."""
    _validar_campos(campos, CAMPOS_CLIENTE_OPERATIVO | CAMPOS_CLIENTE_SENSIBLE, "cliente")
    if "region" in campos:
        config.validar_region(campos["region"])

    operativos = {c: v for c, v in campos.items() if c in CAMPOS_CLIENTE_OPERATIVO}
    sensibles = {c: v for c, v in campos.items() if c in CAMPOS_CLIENTE_SENSIBLE}

    with conectar_pg("centro") as conexion:
        # Siempre se toca el fragmento operativo: confirma que el cliente
        # existe y deja registrada la fecha de la modificación.
        consulta = sql.SQL(
            "UPDATE clientes_operativo SET {}actualizado_en = now() WHERE id = %(id)s"
        ).format(_asignaciones(operativos) + sql.SQL(", ") if operativos else sql.SQL(""))
        if conexion.execute(consulta, {**operativos, "id": cliente_id}).rowcount == 0:
            raise ValidacionError(f"No existe el cliente {cliente_id}")
        if sensibles:
            conexion.execute(
                sql.SQL("UPDATE clientes_sensible SET {} WHERE cliente_id = %(id)s").format(
                    _asignaciones(sensibles)
                ),
                {**sensibles, "id": cliente_id},
            )


def baja_cliente(cliente_id: int) -> None:
    """Baja lógica: el cliente queda inactivo y se eliminan sus datos sensibles.

    No se borra la fila operativa porque envíos y facturas históricos la
    referencian; los datos financieros sí, porque ya no hay motivo para
    conservarlos.
    """
    with conectar_pg("centro") as conexion:
        actualizado = conexion.execute(
            "UPDATE clientes_operativo SET activo = false, actualizado_en = now() WHERE id = %s",
            (cliente_id,),
        )
        if actualizado.rowcount == 0:
            raise ValidacionError(f"No existe el cliente {cliente_id}")
        conexion.execute("DELETE FROM clientes_sensible WHERE cliente_id = %s", (cliente_id,))


def obtener_cliente(cliente_id: int, nodo: str = "centro") -> dict | None:
    """Lee un cliente. En 'centro' devuelve la vista reconstruida (ambos
    fragmentos); en un nodo regional solo existe el fragmento operativo."""
    relacion = "clientes" if nodo == "centro" else "clientes_operativo"
    with conectar_pg(nodo) as conexion:
        return conexion.execute(
            sql.SQL("SELECT * FROM {} WHERE id = %s").format(sql.Identifier(relacion)),
            (cliente_id,),
        ).fetchone()


# ------------------------------------------------------------------------- envíos

_INSERT_ENVIO = """
    INSERT INTO {tabla}
        (region, cliente_id, sucursal_origen_id, sucursal_destino_id,
         vehiculo_id, peso_kg, distancia_km, lluvia_mm, indice_trafico)
    VALUES (%(region)s, %(cliente_id)s, %(sucursal_origen_id)s, %(sucursal_destino_id)s,
            %(vehiculo_id)s, %(peso_kg)s, %(distancia_km)s, %(lluvia_mm)s, %(indice_trafico)s)
    RETURNING id
"""


def _insertar_envio(conexion: psycopg.Connection, datos: dict) -> uuid.UUID:
    """Valida contra la copia local del catálogo e inserta en el fragmento local."""
    cliente = conexion.execute(
        "SELECT activo FROM clientes_operativo WHERE id = %s", (datos["cliente_id"],)
    ).fetchone()
    if cliente is None:
        raise ValidacionError(
            f"El cliente {datos['cliente_id']} no existe en el nodo {datos['region']} "
            "(si es nuevo, la replicación asíncrona puede no haberlo traído todavía)"
        )
    if not cliente["activo"]:
        raise ValidacionError(f"El cliente {datos['cliente_id']} está dado de baja")

    origen = conexion.execute(
        "SELECT region FROM sucursales WHERE id = %s", (datos["sucursal_origen_id"],)
    ).fetchone()
    if origen is None or origen["region"] != datos["region"]:
        raise ValidacionError(
            f"La sucursal de origen {datos['sucursal_origen_id']} no pertenece "
            f"a la región {datos['region']}"
        )

    consulta = sql.SQL(_INSERT_ENVIO).format(
        tabla=sql.Identifier(config.tabla_envios(datos["region"]))
    )
    return conexion.execute(consulta, datos).fetchone()["id"]


def _datos_envio(
    region: str,
    cliente_id: int,
    sucursal_origen_id: int,
    sucursal_destino_id: int,
    peso_kg: float,
    distancia_km: float,
    vehiculo_id: int | None,
    lluvia_mm: float,
    indice_trafico: float,
) -> dict:
    config.validar_region(region)
    return {
        "region": region,
        "cliente_id": cliente_id,
        "sucursal_origen_id": sucursal_origen_id,
        "sucursal_destino_id": sucursal_destino_id,
        "vehiculo_id": vehiculo_id,
        "peso_kg": peso_kg,
        "distancia_km": distancia_km,
        "lluvia_mm": lluvia_mm,
        "indice_trafico": indice_trafico,
    }


def alta_envio(
    *,
    region: str,
    cliente_id: int,
    sucursal_origen_id: int,
    sucursal_destino_id: int,
    peso_kg: float,
    distancia_km: float,
    vehiculo_id: int | None = None,
    lluvia_mm: float = 0,
    indice_trafico: float = 0,
) -> uuid.UUID:
    """Registra un envío en el nodo de su región, sin intervención de Central."""
    datos = _datos_envio(
        region,
        cliente_id,
        sucursal_origen_id,
        sucursal_destino_id,
        peso_kg,
        distancia_km,
        vehiculo_id,
        lluvia_mm,
        indice_trafico,
    )
    with conectar_pg(region) as conexion:
        return _insertar_envio(conexion, datos)


def alta_envio_facturado(
    *,
    region: str,
    cliente_id: int,
    sucursal_origen_id: int,
    sucursal_destino_id: int,
    peso_kg: float,
    distancia_km: float,
    monto: float,
    vehiculo_id: int | None = None,
    lluvia_mm: float = 0,
    indice_trafico: float = 0,
) -> tuple[uuid.UUID, int]:
    """Alta atómica de envío (nodo regional) + factura (pg-centro).

    Devuelve `(envio_id, factura_id)`. Si cualquiera de los dos nodos falla,
    no queda ni el envío ni la factura.
    """
    datos = _datos_envio(
        region,
        cliente_id,
        sucursal_origen_id,
        sucursal_destino_id,
        peso_kg,
        distancia_km,
        vehiculo_id,
        lluvia_mm,
        indice_trafico,
    )
    insertar_factura = """
        INSERT INTO facturas (envio_id, region_envio, cliente_id, monto)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    if region == "centro":
        # Envío y factura conviven en el mismo nodo: alcanza una transacción local.
        with conectar_pg("centro") as conexion:
            envio_id = _insertar_envio(conexion, datos)
            factura = conexion.execute(
                insertar_factura, (envio_id, region, cliente_id, monto)
            ).fetchone()
        return envio_id, factura["id"]

    with transaccion_distribuida(region, "centro") as (regional, central):
        envio_id = _insertar_envio(regional, datos)
        factura = central.execute(
            insertar_factura, (envio_id, region, cliente_id, monto)
        ).fetchone()
    return envio_id, factura["id"]


def modificar_envio(region: str, envio_id: uuid.UUID, /, **campos) -> None:
    """Modifica un envío en su nodo. La región no cambia: es la clave de fragmentación."""
    _validar_campos(campos, CAMPOS_ENVIO_MODIFICABLES, "envío")
    consulta = sql.SQL("UPDATE {} SET {} WHERE id = %(id)s").format(
        sql.Identifier(config.tabla_envios(region)), _asignaciones(campos)
    )
    with conectar_pg(region) as conexion:
        if conexion.execute(consulta, {**campos, "id": envio_id}).rowcount == 0:
            raise ValidacionError(f"No existe el envío {envio_id} en la región {region}")


def baja_envio(region: str, envio_id: uuid.UUID) -> None:
    """Elimina un envío y anula su factura, si la tiene, de forma atómica."""
    borrar = sql.SQL("DELETE FROM {} WHERE id = %s").format(
        sql.Identifier(config.tabla_envios(region))
    )
    anular = "UPDATE facturas SET estado = 'anulada' WHERE envio_id = %s"

    def _ejecutar(regional: psycopg.Connection, central: psycopg.Connection) -> None:
        if regional.execute(borrar, (envio_id,)).rowcount == 0:
            raise ValidacionError(f"No existe el envío {envio_id} en la región {region}")
        central.execute(anular, (envio_id,))

    if region == "centro":
        with conectar_pg("centro") as conexion:
            _ejecutar(conexion, conexion)
    else:
        with transaccion_distribuida(region, "centro") as (regional, central):
            _ejecutar(regional, central)


def obtener_envio(region: str, envio_id: uuid.UUID) -> dict | None:
    consulta = sql.SQL("SELECT * FROM {} WHERE id = %s").format(
        sql.Identifier(config.tabla_envios(region))
    )
    with conectar_pg(region) as conexion:
        return conexion.execute(consulta, (envio_id,)).fetchone()


# -------------------------------------------------------------------- facturación


def registrar_pago(factura_id: int, monto: float, medio: str) -> int:
    """Registra un pago y marca la factura como pagada.

    Se ejecuta en pg-centro, donde el COMMIT solo retorna cuando el standby
    síncrono aplicó la transacción (propiedades ACID con durabilidad en dos nodos).
    """
    with conectar_pg("centro") as conexion:
        factura = conexion.execute(
            "SELECT estado FROM facturas WHERE id = %s FOR UPDATE", (factura_id,)
        ).fetchone()
        if factura is None:
            raise ValidacionError(f"No existe la factura {factura_id}")
        if factura["estado"] != "emitida":
            raise ValidacionError(f"La factura {factura_id} está {factura['estado']}")
        pago = conexion.execute(
            "INSERT INTO pagos (factura_id, monto, medio) VALUES (%s, %s, %s) RETURNING id",
            (factura_id, monto, medio),
        ).fetchone()
        conexion.execute("UPDATE facturas SET estado = 'pagada' WHERE id = %s", (factura_id,))
    return pago["id"]


def obtener_factura_de_envio(envio_id: uuid.UUID) -> dict | None:
    with conectar_pg("centro") as conexion:
        return conexion.execute(
            "SELECT * FROM facturas WHERE envio_id = %s", (envio_id,)
        ).fetchone()
