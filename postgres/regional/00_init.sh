#!/bin/bash
# Inicialización de un nodo regional (pg-norte / pg-sur). REGION llega por
# variable de entorno desde compose.yaml.
(
    set -euo pipefail

    : "${REGION:?falta la variable REGION}"

    ejecutar() {
        psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"
    }

    # Ambos hosts y target_session_attrs=read-write: tras un failover la
    # suscripción se reconecta sola al nodo que haya quedado como primario.
    conexion_central="host=pg-centro,pg-centro-replica port=5432,5432 dbname=${POSTGRES_DB} user=replicador password=${REPLICATION_PASSWORD} target_session_attrs=read-write connect_timeout=5"

    ejecutar -f /sql/comun/01_catalogo.sql
    ejecutar -v tabla="envios_${REGION}" -v clausula_particion= -f /sql/comun/02_envios.sql
    ejecutar -v tabla="envios_${REGION}" -v region="$REGION" -f /sql/regional/01_fragmento.sql
    ejecutar -v suscripcion="sub_${REGION}" -v conexion="$conexion_central" \
        -f /sql/regional/02_suscripcion.sql
)
