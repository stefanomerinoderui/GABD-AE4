#!/usr/bin/env python3
"""Punto de entrada multiplataforma para operar el clúster de Logística Federal.

Requisitos en el host: Python >= 3.10 y Docker con Compose v2. Nada más.
    Linux/macOS:  python3 tareas.py <comando>
    Windows:      py tareas.py <comando>
Ejecute sin argumentos para ver todos los comandos.
"""

import argparse
import shutil
import sys

from operaciones import (
    backups,
    caida_cassandra,
    failover,
    particion_red,
    recuperacion_wal,
    reincorporar,
    restaurar,
)
from operaciones.comun import RAIZ, OperacionError, compose, ejecutar, en_contenedor, titulo

VERSION_MINIMA = (3, 10)
CODIGO_SEED = """
import logging
logging.basicConfig(level=logging.INFO)
from logistica import etl, resumen, semilla
print(semilla.sembrar(reiniciar=True))
print(etl.ejecutar_etl())
print(resumen.refrescar())
"""
CODIGO_ETL = "from logistica import etl; print(etl.ejecutar_etl())"
CODIGO_RESUMEN = "from logistica import resumen; print(resumen.refrescar())"


def asegurar_env() -> None:
    destino, plantilla = RAIZ / ".env", RAIZ / ".env.example"
    if not destino.exists():
        shutil.copy(plantilla, destino)
        print("Se creó .env a partir de .env.example")


def cmd_up(_args) -> None:
    asegurar_env()
    compose("up", "-d", "--build", "--wait")


def cmd_down(_args) -> None:
    compose("--profile", "restore", "down")


def cmd_reset(args) -> None:
    if not args.si:
        respuesta = input(
            "Esto borra TODOS los datos (volúmenes incluidos). Escriba 'si' para continuar: "
        )
        if respuesta.strip().lower() != "si":
            raise OperacionError("Cancelado.")
    compose("--profile", "restore", "down", "-v")
    cmd_up(args)


def cmd_seed(_args) -> None:
    en_contenedor("jupyter", "python", "-c", CODIGO_SEED)


def cmd_etl(_args) -> None:
    en_contenedor("jupyter", "python", "-c", CODIGO_ETL)


def cmd_refrescar_resumen(_args) -> None:
    en_contenedor("jupyter", "python", "-c", CODIGO_RESUMEN)


def cmd_test(_args) -> int:
    return en_contenedor(
        "jupyter", "pytest", "-q", "-p", "no:cacheprovider", check=False
    ).returncode


def cmd_notebooks(_args) -> None:
    for cuaderno in sorted((RAIZ / "notebooks").glob("*.ipynb")):
        titulo(cuaderno.name)
        en_contenedor(
            "jupyter", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--stdout",
            f"notebooks/{cuaderno.name}", capturar=True,
        )  # fmt: skip
        print("OK")


def cmd_lint(_args) -> int:
    """ruff y shellcheck se usan si están instalados; compose config siempre."""
    fallos = 0
    herramientas = {
        "ruff": [["ruff", "check", "."], ["ruff", "format", "--check", "."]],
        "shellcheck": [
            ["shellcheck", "-x", *map(str, sorted(RAIZ.glob("docker/postgres/*.sh")))],
            ["shellcheck", "-x", *map(str, sorted(RAIZ.glob("postgres/*/00_init.sh")))],
        ],
    }
    for nombre, comandos in herramientas.items():
        if shutil.which(nombre) is None:
            print(f"Aviso: {nombre} no está instalado; se omite.")
            continue
        for comando in comandos:
            fallos += ejecutar(comando, check=False).returncode != 0
    fallos += compose("config", "-q", check=False).returncode != 0
    return 1 if fallos else 0


def cmd_failover(args) -> None:
    failover.ejecutar(degradado=args.degradado)


def cmd_caida_cassandra(args) -> None:
    caida_cassandra.ejecutar(args.nodo)


def cmd_restore(args) -> None:
    restaurar.restaurar(args.instante)


COMANDOS = [
    ("up", cmd_up, "Construye y levanta todo el clúster (~3 min la primera vez)", []),
    ("down", cmd_down, "Detiene el clúster conservando los datos", []),
    ("reset", cmd_reset, "Destruye TODO (volúmenes incluidos) y levanta desde cero",
     [(("--si",), {"action": "store_true", "help": "no pedir confirmación"})]),
    ("seed", cmd_seed, "Carga datos sintéticos (reemplaza los existentes) y el data warehouse", []),
    ("etl", cmd_etl, "Recarga el data warehouse", []),
    ("refrescar-resumen", cmd_refrescar_resumen,
     "Fase 3: refresca la vista materializada de envíos (CONCURRENTLY si es posible)", []),
    ("test", cmd_test, "Tests de integración contra el clúster", []),
    ("lint", cmd_lint, "ruff + shellcheck (si están instalados) + validación de compose", []),
    ("notebooks", cmd_notebooks, "Ejecuta los notebooks de punta a punta (sin guardar salidas)", []),
    ("failover", cmd_failover, "Fase 2: cae el primario de Central y se promueve el standby",
     [(("--degradado",), {"action": "store_true",
                          "help": "desactiva el requisito de standby síncrono (riesgo de pérdida)"})]),
    ("reincorporar", lambda _a: reincorporar.ejecutar(), "Fase 2: reincorpora el antiguo primario como standby", []),
    ("particion-red", lambda _a: particion_red.ejecutar(), "Fase 2: aísla el Norte y muestra CAP", []),
    ("caida-cassandra", cmd_caida_cassandra, "Fase 2: cae un nodo de Cassandra (ONE/QUORUM vs ALL)",
     [(("--nodo",), {"default": "cassandra-sur", "help": "servicio a detener (por defecto cassandra-sur)"})]),
    ("recuperacion-wal", lambda _a: recuperacion_wal.ejecutar(), "Fase 2: kill -9 del nodo Sur y recuperación REDO/UNDO", []),
    ("backup", lambda _a: backups.completo(), "Backup completo de PostgreSQL (primario de Central)", []),
    ("backup-incremental", lambda _a: backups.incremental(), "Backup incremental de PostgreSQL", []),
    ("backup-cassandra", lambda _a: backups.cassandra(), "Snapshot de los tres nodos de Cassandra", []),
    ("restore", cmd_restore, "Restaura la cadena de backups en una instancia aparte (PITR)",
     [(("--instante",), {"help": "AAAA-MM-DD HH:MM:SS+00 (por defecto: todo el WAL archivado)"})]),
    ("restore-limpiar", lambda _a: restaurar.limpiar(), "Elimina la instancia de restauración de prueba", []),
]  # fmt: skip


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operación del clúster de Logística Federal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--debug", action="store_true", help="muestra el traceback completo ante errores"
    )
    sub = parser.add_subparsers(dest="comando", metavar="comando")
    for nombre, funcion, ayuda, opciones in COMANDOS:
        subparser = sub.add_parser(nombre, help=ayuda, description=ayuda)
        for banderas, kwargs in opciones:
            subparser.add_argument(*banderas, **kwargs)
        subparser.set_defaults(funcion=funcion)
    return parser


def verificar_entorno() -> None:
    if sys.version_info < VERSION_MINIMA:
        raise OperacionError(f"Se requiere Python >= {'.'.join(map(str, VERSION_MINIMA))}.")
    if shutil.which("docker") is None:
        raise OperacionError("No se encontró 'docker'. Instale Docker (Desktop en Windows/macOS).")


def main(argv: list[str] | None = None) -> int:
    # Consolas de Windows: evita UnicodeEncodeError con acentos y símbolos.
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not args.comando:
        parser.print_help()
        return 0
    try:
        verificar_entorno()
        return args.funcion(args) or 0
    except OperacionError as error:
        if args.debug:
            raise
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
