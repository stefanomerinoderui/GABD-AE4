-- Conexión: Central (pg-centro)
-- Fragmentación horizontal, vertical y replicación.

-- 1. Horizontal: filas por fragmento (tableoid indica la partición física).
SELECT tableoid::regclass AS fragmento, region, count(*) AS filas
FROM envios GROUP BY 1, 2 ORDER BY 1;

-- 2. Particiones de envios y su tipo (local o foránea vía postgres_fdw).
SELECT c.relname AS particion, c.relkind AS tipo, pg_get_expr(c.relpartbound, c.oid) AS limite
FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
WHERE i.inhparent = 'envios'::regclass ORDER BY 1;

-- 3. Poda de particiones: un envío de la región norte solo toca envios_norte.
EXPLAIN SELECT * FROM envios WHERE region = 'norte';

-- 4. Vertical: la vista clientes une la parte operativa (replicada) y la sensible (solo Central).
SELECT * FROM clientes LIMIT 10;
SELECT count(*) AS operativo FROM clientes_operativo;
SELECT count(*) AS sensible  FROM clientes_sensible;

-- 5. Replicación física síncrona: standby y modo.
SELECT application_name, state, sync_state, replay_lag FROM pg_stat_replication;
SHOW synchronous_standby_names;
SHOW synchronous_commit;

-- 6. Replicación lógica del catálogo: publicación y slots (con failover).
SELECT * FROM pg_publication;
SELECT slot_name, slot_type, active, failover FROM pg_replication_slots;
