-- =============================================================================
-- Definición única de la relación Envios, reutilizada por los tres nodos.
-- Variables psql:
--   :tabla               nombre de la tabla a crear
--   :clausula_particion  'PARTITION BY LIST (region)' en pg-centro (tabla global)
--                        o vacío en los nodos regionales (fragmento físico)
--
-- La clave es UUID v7: cada nodo genera identificadores sin coordinarse con
-- los demás (autonomía local) y, al estar ordenados por tiempo, no fragmentan
-- el índice B-tree como lo haría un UUID aleatorio.
-- No hay FK a clientes: el catálogo llega por replicación asíncrona y una FK
-- rechazaría envíos de clientes recién creados. La validación la hace el ABM.
-- =============================================================================

CREATE TABLE :"tabla" (
    id                  uuid NOT NULL DEFAULT uuidv7(),
    region              text NOT NULL,
    cliente_id          bigint NOT NULL,
    sucursal_origen_id  integer NOT NULL,
    sucursal_destino_id integer NOT NULL,
    vehiculo_id         integer,
    peso_kg             numeric(8, 2) NOT NULL CHECK (peso_kg > 0),
    distancia_km        numeric(8, 1) NOT NULL CHECK (distancia_km >= 0),
    -- Condiciones registradas al despachar; alimentan el modelo de ETA.
    lluvia_mm           numeric(5, 1) NOT NULL DEFAULT 0 CHECK (lluvia_mm >= 0),
    indice_trafico      numeric(3, 2) NOT NULL DEFAULT 0 CHECK (indice_trafico BETWEEN 0 AND 1),
    estado              text NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'en_transito', 'entregado', 'cancelado')),
    fecha_alta          timestamptz NOT NULL DEFAULT now(),
    fecha_entrega       timestamptz,
    CHECK (fecha_entrega IS NULL OR fecha_entrega >= fecha_alta)
) :clausula_particion;
