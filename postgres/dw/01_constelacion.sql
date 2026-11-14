-- =============================================================================
-- Data warehouse: esquema de constelación de hechos.
-- Dos tablas de hechos (entregas e incidentes) comparten las dimensiones
-- conformadas Tiempo, Geografía y Vehículo. Lo carga src/logistica/etl.py.
-- =============================================================================

CREATE TABLE dim_tiempo (
    tiempo_id         integer PRIMARY KEY,          -- clave inteligente AAAAMMDD
    fecha             date NOT NULL UNIQUE,
    dia               smallint NOT NULL,
    mes               smallint NOT NULL,
    nombre_mes        text NOT NULL,
    trimestre         smallint NOT NULL,
    anio              smallint NOT NULL,
    dia_semana        smallint NOT NULL,            -- 1 = lunes ... 7 = domingo
    es_fin_de_semana  boolean NOT NULL
);

-- Jerarquía Región > Provincia > Ciudad (permite roll-up y drill-down).
CREATE TABLE dim_geografia (
    geografia_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region       text NOT NULL,
    provincia    text NOT NULL,
    ciudad       text NOT NULL,
    UNIQUE (region, provincia, ciudad)
);

CREATE TABLE dim_vehiculo (
    vehiculo_id  integer PRIMARY KEY,               -- clave del sistema operacional
    patente      text NOT NULL,
    tipo         text NOT NULL,
    capacidad_kg integer NOT NULL,
    region_base  text NOT NULL
);

-- Granularidad: un envío entregado.
CREATE TABLE hechos_entregas (
    envio_id             uuid PRIMARY KEY,          -- dimensión degenerada
    tiempo_id            integer NOT NULL REFERENCES dim_tiempo (tiempo_id),
    geografia_origen_id  integer NOT NULL REFERENCES dim_geografia (geografia_id),
    geografia_destino_id integer NOT NULL REFERENCES dim_geografia (geografia_id),
    vehiculo_id          integer REFERENCES dim_vehiculo (vehiculo_id),
    hora_despacho        smallint NOT NULL,
    peso_kg              numeric(8, 2) NOT NULL,
    distancia_km         numeric(8, 1) NOT NULL,
    lluvia_mm            numeric(5, 1) NOT NULL,
    indice_trafico       numeric(3, 2) NOT NULL,
    horas_entrega        numeric(8, 2) NOT NULL,
    monto                numeric(12, 2)
);

-- Granularidad: un incidente reportado en ruta.
CREATE TABLE hechos_incidentes (
    incidente_id uuid PRIMARY KEY,                  -- dimensión degenerada
    tiempo_id    integer NOT NULL REFERENCES dim_tiempo (tiempo_id),
    geografia_id integer NOT NULL REFERENCES dim_geografia (geografia_id),
    vehiculo_id  integer REFERENCES dim_vehiculo (vehiculo_id),
    tipo         text NOT NULL,
    demora_min   integer NOT NULL,
    lat          double precision NOT NULL,
    lon          double precision NOT NULL
);

-- Las consultas OLAP filtran y agrupan por las claves de dimensión.
CREATE INDEX idx_entregas_tiempo ON hechos_entregas (tiempo_id);
CREATE INDEX idx_entregas_origen ON hechos_entregas (geografia_origen_id);
CREATE INDEX idx_incidentes_tiempo ON hechos_incidentes (tiempo_id);
CREATE INDEX idx_incidentes_geografia ON hechos_incidentes (geografia_id);
