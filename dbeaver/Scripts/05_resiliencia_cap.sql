-- Conexión: Central (pg-centro), salvo donde se indique.
-- Estado del clúster para las demostraciones de la Fase 2 (comandos en el README principal).

-- 1. ¿Este nodo es primario o standby? (false = primario)
SELECT pg_is_in_recovery() AS es_standby, inet_server_addr() AS ip;

-- 2. Standby síncrono conectado y su retraso.
SELECT application_name, client_addr, state, sync_state,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS bytes_pendientes
FROM pg_stat_replication;

-- 3. Posición actual del WAL y último checkpoint (recuperación REDO).
SELECT pg_current_wal_lsn() AS lsn_actual;
SELECT checkpoint_lsn, redo_lsn, checkpoint_time FROM pg_control_checkpoint();

-- 4. Archivado continuo de WAL (RPO <= 15 min).
SELECT archived_count, failed_count, last_archived_wal, last_archived_time FROM pg_stat_archiver;
SHOW archive_timeout;

-- 5. Commits esperando al standby síncrono (aparecen si el standby cae: comportamiento CP).
SELECT pid, wait_event, state, left(query, 60) AS consulta
FROM pg_stat_activity WHERE wait_event = 'SyncRep';

-- 6. Transacciones preparadas (two-phase commit) pendientes.
SELECT gid, prepared, owner, database FROM pg_prepared_xacts;

-- 7. Suscripciones lógicas del catálogo: ejecutar en Norte (pg-norte) o Sur (pg-sur).
-- SELECT subname, subenabled, subfailover FROM pg_subscription;
-- SELECT * FROM pg_stat_subscription;
