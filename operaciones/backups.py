"""Backups de PostgreSQL (completo e incremental) y de Cassandra.

Política (ver README): completo semanal + incremental horario + archivado continuo de WAL.
  RPO <= 15 min   un segmento de WAL se archiva como máximo cada 900 s (archive_timeout).
  RTO <= 2 h      se mide en `restaurar`.
Destino: volumen `backups` (simula el almacenamiento frío; ver operaciones/programacion.md).
"""

from datetime import UTC, datetime

from operaciones.comun import (
    OperacionError,
    cargar_env,
    en_contenedor,
    requerir_servicio,
    servicio_primario,
    titulo,
)

RAIZ_BACKUPS = "/backups/centro/bk"
NODOS_CASSANDRA = ("cassandra-norte", "cassandra-centro", "cassandra-sur")

# Se ejecuta DENTRO del contenedor de Cassandra: copia el snapshot al repositorio.
COPIAR_SNAPSHOT = r"""
set -eu
destino=/backups/cassandra/{nodo}/{etiqueta}
cd /var/lib/cassandra/data
find tracking -type d -path '*/snapshots/{etiqueta}' | while read -r origen; do
    tabla=$(echo "$origen" | cut -d/ -f2 | cut -d- -f1)
    mkdir -p "$destino/$tabla" && cp -r "$origen"/. "$destino/$tabla/"
done
du -sh "$destino"
"""


def marca_de_tiempo() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def backups_de_postgres(nombres: list[str]) -> list[str]:
    """Filtra y ordena (cronológicamente) los directorios de backup válidos."""
    return sorted(n for n in nombres if n.endswith(("_completo", "_incremental")))


def ultimo_backup(nombres: list[str]) -> str | None:
    """Backup más reciente de la cadena: base sobre la que se toma el incremental."""
    validos = backups_de_postgres(nombres)
    return validos[-1] if validos else None


def listar_backups(servicio: str) -> list[str]:
    resultado = en_contenedor(
        servicio, "ls", "-1", RAIZ_BACKUPS, usuario="postgres", capturar=True, check=False
    )
    return resultado.stdout.split() if resultado.returncode == 0 else []


def _pg_basebackup(servicio: str, destino: str, *extra: str) -> None:
    usuario = cargar_env().get("POSTGRES_USER", "logistica")
    salida = en_contenedor(
        servicio,
        "pg_basebackup",
        f"--username={usuario}",
        f"--pgdata={destino}",
        "--format=plain",
        "--wal-method=stream",
        "--checkpoint=fast",
        *extra,
        usuario="postgres",
        capturar=True,
    ).stdout
    print("\n".join(salida.strip().splitlines()[-3:]))


def completo(servicio: str | None = None) -> None:
    """Backup completo con pg_basebackup (del primario actual si no se indica otro)."""
    servicio = servicio or servicio_primario()
    requerir_servicio(servicio)
    destino = f"{RAIZ_BACKUPS}/{marca_de_tiempo()}_completo"
    titulo(f"Backup completo de {servicio} -> {destino}")
    _pg_basebackup(servicio, destino, "--label=completo-semanal", "--progress", "--verbose")
    en_contenedor(servicio, "du", "-sh", destino, usuario="postgres")


def incremental(servicio: str | None = None) -> None:
    """Incremental: solo los bloques modificados desde el backup anterior (summarize_wal)."""
    servicio = servicio or servicio_primario()
    requerir_servicio(servicio)
    previo = ultimo_backup(listar_backups(servicio))
    if previo is None:
        raise OperacionError("No hay un backup previo: ejecute 'backup' primero.")
    destino = f"{RAIZ_BACKUPS}/{marca_de_tiempo()}_incremental"
    titulo(f"Incremental de {servicio} sobre {previo}")
    _pg_basebackup(
        servicio,
        destino,
        f"--incremental={RAIZ_BACKUPS}/{previo}/backup_manifest",
        "--label=incremental-horario",
    )
    en_contenedor(servicio, "du", "-sh", f"{RAIZ_BACKUPS}/{previo}", destino, usuario="postgres")


def cassandra() -> None:
    """Snapshot de cada nodo (hard links, instantáneo) copiado al repositorio.

    Con RF = 3 cada nodo tiene una réplica completa; se toman los tres para tolerar que
    uno estuviera desactualizado en el momento del snapshot.
    """
    etiqueta = f"snap_{marca_de_tiempo()}"
    for nodo in NODOS_CASSANDRA:
        requerir_servicio(nodo)
        titulo(nodo)
        en_contenedor(nodo, "nodetool", "enablebackup")
        en_contenedor(nodo, "nodetool", "snapshot", "--tag", etiqueta, "tracking", capturar=True)
        en_contenedor(
            nodo,
            "bash",
            "-c",
            COPIAR_SNAPSHOT.format(nodo=nodo, etiqueta=etiqueta),
            usuario="root",
        )
