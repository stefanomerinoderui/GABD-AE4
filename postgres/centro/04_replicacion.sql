-- =============================================================================
-- Replicación de pg-centro. Variable psql: :clave_replicacion
-- =============================================================================

CREATE ROLE replicador WITH REPLICATION LOGIN PASSWORD :'clave_replicacion';

-- 1) Replicación LÓGICA, ASÍNCRONA y PARCIAL hacia las sucursales: solo el
--    catálogo y el fragmento operativo de clientes. clientes_sensible,
--    facturas y pagos quedan fuera de la publicación.
GRANT SELECT ON sucursales, vehiculos, clientes_operativo TO replicador;
CREATE PUBLICATION pub_catalogo FOR TABLE sucursales, vehiculos, clientes_operativo;

-- 2) Replicación FÍSICA, SÍNCRONA y TOTAL hacia pg-centro-replica.
--    El slot retiene el WAL que el standby todavía no consumió.
SELECT pg_create_physical_replication_slot('standby_slot');

-- ALTER SYSTEM escribe postgresql.auto.conf y rige desde el reinicio que hace
-- el entrypoint al terminar la inicialización (activarlo antes colgaría estos
-- mismos scripts esperando a un standby que aún no existe).
--
-- Quórum: un COMMIT solo se confirma al cliente cuando al menos un standby lo
-- aplicó (remote_apply). Sin standby no hay confirmación: se sacrifica
-- disponibilidad para no perder ni desfasar transacciones financieras (CP).
-- Se listan ambos nombres para que la regla valga también con roles invertidos.
ALTER SYSTEM SET synchronous_standby_names = 'ANY 1 (pg_centro, pg_centro_replica)';
ALTER SYSTEM SET synchronous_commit = 'remote_apply';

-- Las sucursales nunca reciben un cambio que el standby todavía no tenga, de
-- modo que tras un failover no quedan "adelantadas" respecto del nuevo primario.
ALTER SYSTEM SET synchronized_standby_slots = 'standby_slot';
