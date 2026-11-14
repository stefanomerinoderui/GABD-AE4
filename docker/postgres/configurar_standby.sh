#!/bin/bash
# Deja el directorio de datos listo para arrancar como standby en streaming.
# Uso: configurar_standby <host_primario> <application_name>
# El application_name es el que el primario espera en synchronous_standby_names.
set -euo pipefail

host_primario="${1:?falta el host del primario}"
nombre_aplicacion="${2:?falta el application_name}"

touch "$PGDATA/standby.signal"
# dbname es obligatorio para que el standby sincronice los slots lógicos
# (sync_replication_slots) y las suscripciones sobrevivan al failover.
cat >> "$PGDATA/postgresql.auto.conf" <<CONF
primary_conninfo = 'host=${host_primario} port=5432 user=replicador password=${REPLICATION_PASSWORD} application_name=${nombre_aplicacion} dbname=${POSTGRES_DB}'
primary_slot_name = 'standby_slot'
CONF
