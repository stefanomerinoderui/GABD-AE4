#!/bin/bash
# Entrypoint de pg-centro-replica: en el primer arranque clona al primario con
# pg_basebackup y queda como standby; luego delega en el entrypoint oficial.
set -euo pipefail

PRIMARIO="${PRIMARIO:-pg-centro}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "iniciar_standby: esperando a ${PRIMARIO}..."
    until pg_isready -h "$PRIMARIO" -q; do sleep 2; done

    install -d -o postgres -g postgres -m 700 "$PGDATA"
    PGPASSWORD="$REPLICATION_PASSWORD" gosu postgres pg_basebackup \
        -h "$PRIMARIO" -U replicador -D "$PGDATA" \
        -X stream -S standby_slot -c fast
    gosu postgres configurar_standby "$PRIMARIO" pg_centro_replica
    echo "iniciar_standby: copia base completa, arrancando como standby"
fi

exec docker-entrypoint.sh "$@"
