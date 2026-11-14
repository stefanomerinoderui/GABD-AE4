-- =============================================================================
-- Suscripción al catálogo de pg-centro. Variables psql: :suscripcion, :conexion
--
-- failover = true: el slot lógico se sincroniza en pg-centro-replica, por lo
-- que la suscripción continúa sin pérdida si la réplica es promovida.
-- =============================================================================

CREATE SUBSCRIPTION :"suscripcion"
    CONNECTION :'conexion'
    PUBLICATION pub_catalogo
    WITH (failover = true);
