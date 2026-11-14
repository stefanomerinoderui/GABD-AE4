-- =============================================================================
-- pg-centro: objetos que existen únicamente en la sede Central.
-- =============================================================================

-- Fragmento vertical "sensible" de Clientes. No se publica ni se replica a las
-- sucursales: una intrusión en un depósito no expone datos financieros.
CREATE TABLE clientes_sensible (
    cliente_id     bigint PRIMARY KEY REFERENCES clientes_operativo (id) ON DELETE CASCADE,
    token_tarjeta  text NOT NULL,   -- token del procesador de pagos, nunca el PAN
    ultimos4       char(4) NOT NULL CHECK (ultimos4 ~ '^[0-9]{4}$'),
    limite_credito numeric(12, 2) NOT NULL CHECK (limite_credito >= 0),
    scoring        integer NOT NULL CHECK (scoring BETWEEN 0 AND 1000)
);

-- Regla de reconstrucción de la fragmentación vertical: Clientes se recupera
-- con un JOIN por la clave primaria, presente en ambos fragmentos.
CREATE VIEW clientes AS
SELECT o.*, s.token_tarjeta, s.ultimos4, s.limite_credito, s.scoring
FROM clientes_operativo AS o
LEFT JOIN clientes_sensible AS s ON s.cliente_id = o.id;

-- Facturación: solo en Central y con replicación síncrona (ver 04_replicacion).
-- envio_id no puede ser FK porque el envío vive en otro nodo: la atomicidad
-- envío + factura la garantiza el two-phase commit del ABM.
CREATE TABLE facturas (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    envio_id     uuid NOT NULL UNIQUE,
    region_envio text NOT NULL CHECK (region_envio IN ('norte', 'centro', 'sur')),
    cliente_id   bigint NOT NULL REFERENCES clientes_operativo (id),
    monto        numeric(12, 2) NOT NULL CHECK (monto > 0),
    estado       text NOT NULL DEFAULT 'emitida'
        CHECK (estado IN ('emitida', 'pagada', 'anulada')),
    emitida_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pagos (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factura_id bigint NOT NULL REFERENCES facturas (id),
    monto      numeric(12, 2) NOT NULL CHECK (monto > 0),
    medio      text NOT NULL CHECK (medio IN ('tarjeta', 'transferencia', 'efectivo')),
    pagado_en  timestamptz NOT NULL DEFAULT now()
);
