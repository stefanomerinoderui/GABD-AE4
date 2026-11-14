#!/bin/bash
# Inicialización de pg-centro (sede Central). Lo ejecuta el entrypoint oficial
# una sola vez, sobre un directorio de datos vacío.
(
    set -euo pipefail

    ejecutar() {
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"
    }

    ejecutar -f /sql/comun/01_catalogo.sql
    ejecutar -v tabla=envios -v clausula_particion='PARTITION BY LIST (region)' \
        -f /sql/comun/02_envios.sql
    ejecutar -f /sql/centro/01_esquema.sql
    ejecutar -v usuario="$POSTGRES_USER" -v clave="$POSTGRES_PASSWORD" -v base="$POSTGRES_DB" \
        -f /sql/centro/02_fragmentacion.sql
    ejecutar -f /sql/centro/03_datos_catalogo.sql
    ejecutar -v clave_replicacion="$REPLICATION_PASSWORD" -f /sql/centro/04_replicacion.sql

    # La regla por defecto de la imagen ("host all all all") no cubre las
    # conexiones de replicación física, que usan la pseudo-base "replication".
    echo "host replication replicador all scram-sha-256" >> "$PGDATA/pg_hba.conf"
)
