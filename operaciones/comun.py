"""Utilidades compartidas: invocación de Docker, psql/cqlsh y esperas."""

import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROYECTO = "logistica-federal"  # `name:` de compose.yaml (prefijo de volúmenes)
RED = "logistica_red"
PRIMARIOS_CENTRO = ("pg-centro", "pg-centro-replica")


class OperacionError(Exception):
    """Falla esperable de una operación (se informa sin traceback)."""


def cargar_env(ruta: Path | None = None) -> dict[str, str]:
    """Lee `.env` (formato CLAVE=VALOR, con comentarios `#`). Si falta, devuelve {}."""
    ruta = ruta or RAIZ / ".env"
    if not ruta.exists():
        return {}
    entorno = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        entorno[clave.strip()] = valor.strip().strip("\"'")
    return entorno


def _usuario_y_base() -> tuple[str, str]:
    env = cargar_env()
    return env.get("POSTGRES_USER", "logistica"), env.get("POSTGRES_DB", "logistica")


def titulo(texto: str) -> None:
    print(f"\n=== {texto} ===", flush=True)


def ejecutar(
    comando: list[str],
    *,
    check: bool = True,
    capturar: bool = False,
    stdin: int | None = subprocess.DEVNULL,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Ejecuta un comando SIN shell (idéntico en Windows y Linux).

    Con `capturar=True` devuelve stdout y stderr combinados en `.stdout`; si no, la
    salida se muestra en vivo. Con `check=True` una salida ≠ 0 lanza OperacionError.
    """
    sys.stdout.flush()
    try:
        resultado = subprocess.run(
            comando,
            cwd=RAIZ,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=stdin,
            stdout=subprocess.PIPE if capturar else None,
            stderr=subprocess.STDOUT if capturar else None,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise OperacionError(
            f"No se encontró el comando {comando[0]!r}. ¿Está instalado?"
        ) from error
    if check and resultado.returncode != 0:
        detalle = f"\n{resultado.stdout.strip()}" if capturar and resultado.stdout else ""
        raise OperacionError(
            f"Falló (código {resultado.returncode}): {' '.join(comando[:6])}...{detalle}"
        )
    return resultado


def docker(*args: str, **opciones) -> subprocess.CompletedProcess:
    return ejecutar(["docker", *args], **opciones)


def compose(*args: str, **opciones) -> subprocess.CompletedProcess:
    return ejecutar(["docker", "compose", *args], **opciones)


def comando_en(servicio: str, *comando: str, usuario: str | None = None) -> list[str]:
    """Línea de comandos `docker compose exec -T` (útil también para Popen)."""
    opciones = ["-u", usuario] if usuario else []
    return ["docker", "compose", "exec", "-T", *opciones, servicio, *comando]


def en_contenedor(servicio: str, *comando: str, usuario: str | None = None, **opciones):
    return ejecutar(comando_en(servicio, *comando, usuario=usuario), **opciones)


def argumentos_psql(*argumentos: str) -> list[str]:
    usuario, base = _usuario_y_base()
    return ["psql", "-U", usuario, "-d", base, "-v", "ON_ERROR_STOP=1", *argumentos]


def psql(servicio: str, *sentencias: str, silencioso: bool = False, **opciones):
    """Ejecuta una o más sentencias SQL (un `-c` por sentencia) y muestra el resultado.

    Con `silencioso=True` no muestra nada (usa `-q` y descarta la salida).
    """
    argumentos: list[str] = ["-X", "-q"] if silencioso else []
    for sentencia in sentencias:
        argumentos += ["-c", sentencia]
    if silencioso:
        opciones["capturar"] = True
    return en_contenedor(servicio, *argumentos_psql(*argumentos), **opciones)


def consulta(servicio: str, sql: str) -> str:
    """Valor escalar de una consulta, sin formato (psql -A -t)."""
    resultado = en_contenedor(
        servicio, *argumentos_psql("-X", "-A", "-t", "-c", sql), capturar=True
    )
    return resultado.stdout.strip()


def cql(servicio: str, texto: str, **opciones):
    return en_contenedor(servicio, "cqlsh", "-e", texto, **opciones)


def esperar(descripcion: str, condicion: Callable[[], bool], *, timeout: int = 120) -> None:
    """Reintenta `condicion` cada segundo; los errores cuentan como 'todavía no'."""
    limite = time.monotonic() + timeout
    while True:
        try:
            if condicion():
                return
        except (OperacionError, subprocess.SubprocessError):
            pass
        if time.monotonic() > limite:
            raise OperacionError(f"Tiempo agotado esperando: {descripcion}")
        time.sleep(1)


def esperar_valor(servicio: str, sql: str, esperado: str, *, timeout: int = 120) -> None:
    esperar(
        f"{sql} = {esperado} en {servicio}",
        lambda: consulta(servicio, sql) == esperado,
        timeout=timeout,
    )


def id_contenedor(servicio: str) -> str:
    salida = compose("ps", "-q", servicio, capturar=True).stdout.strip()
    if not salida:
        raise OperacionError(f"El servicio {servicio} no tiene contenedor. Ejecute 'up' primero.")
    return salida.splitlines()[0]


def servicio_en_ejecucion(servicio: str) -> bool:
    salida = compose("ps", "--status", "running", "-q", servicio, capturar=True, check=False)
    return bool(salida.stdout.strip())


def requerir_servicio(servicio: str) -> None:
    if not servicio_en_ejecucion(servicio):
        raise OperacionError(f"El servicio {servicio} no está en ejecución. Ejecute 'up' primero.")


def servicio_primario() -> str:
    """Nodo de Central que hoy acepta escrituras (cambia tras un failover)."""
    for servicio in PRIMARIOS_CENTRO:
        if (
            servicio_en_ejecucion(servicio)
            and consulta(servicio, "SELECT pg_is_in_recovery()") == "f"
        ):
            return servicio
    raise OperacionError("Ningún nodo de Central está actuando como primario.")


def lineas_que_coinciden(texto: str, patron: str) -> list[str]:
    """Líneas de `texto` que cumplen la expresión regular (reemplazo portable de grep)."""
    regex = re.compile(patron)
    return [linea for linea in texto.splitlines() if regex.search(linea)]


def estado_nodos_cassandra(salida_nodetool: str) -> list[str]:
    """Líneas de `nodetool status` con el estado de cada nodo (UN = arriba, DN = caído)."""
    return lineas_que_coinciden(salida_nodetool, r"^(UN|DN|UL|DL|UJ|DJ|UM|DM)\s")


def nodos_cassandra_arriba(servicio: str) -> int:
    salida = en_contenedor(servicio, "nodetool", "status", capturar=True).stdout
    return sum(1 for linea in estado_nodos_cassandra(salida) if linea.startswith("UN"))
