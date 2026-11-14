-- =============================================================================
-- Subsistema NoSQL de trazabilidad (modelo de familia de columnas).
-- Diseño guiado por consultas: una tabla por patrón de acceso.
-- =============================================================================

-- RF = 3 sobre un anillo de 3 nodos (un rack por región): cada nodo guarda una
-- réplica completa. Con consistencia ONE cualquier nodo aislado sigue
-- aceptando lecturas y escrituras (AP); las réplicas convergen después por
-- hinted handoff, read repair y nodetool repair (consistencia eventual, BASE).
CREATE KEYSPACE IF NOT EXISTS tracking
    WITH replication = {'class': 'NetworkTopologyStrategy', 'logistica': 3}
    AND durable_writes = true;

-- Q1: "¿por dónde pasó este paquete?" -> historial más reciente primero.
-- Clave de partición = id_paquete: el sharding por hash reparte los paquetes
-- en el anillo y cada historial (acotado a decenas de eventos) queda en una
-- única partición, que se lee con un solo acceso.
CREATE TABLE IF NOT EXISTS tracking.eventos_por_paquete (
    id_paquete  uuid,
    ts          timestamp,
    tipo        text,
    region      text,
    sucursal_id int,
    lat         double,
    lon         double,
    detalle     text,
    PRIMARY KEY ((id_paquete), ts)
) WITH CLUSTERING ORDER BY (ts DESC);

-- Q2: "recorrido y temperatura de un camión en un día".
-- La telemetría de un camión no tiene cota, así que se parte por ventana de
-- tiempo (camión, día) para que ninguna partición crezca sin límite.
-- TWCS + TTL de 90 días: los SSTables viejos se descartan enteros.
CREATE TABLE IF NOT EXISTS tracking.telemetria_por_camion (
    vehiculo_id   int,
    dia           date,
    ts            timestamp,
    lat           double,
    lon           double,
    velocidad_kmh float,
    temperatura_c float,
    PRIMARY KEY ((vehiculo_id, dia), ts)
) WITH CLUSTERING ORDER BY (ts DESC)
    AND default_time_to_live = 7776000
    AND compaction = {
        'class': 'TimeWindowCompactionStrategy',
        'compaction_window_unit': 'DAYS',
        'compaction_window_size': 1
    };

-- Q3: "incidentes de una región en un mes" (fuente de la minería espacial).
CREATE TABLE IF NOT EXISTS tracking.incidentes_por_region (
    region       text,
    anio_mes     text,          -- 'AAAA-MM'
    ts           timestamp,
    id_incidente uuid,
    tipo         text,
    demora_min   int,
    vehiculo_id  int,
    sucursal_id  int,
    lat          double,
    lon          double,
    PRIMARY KEY ((region, anio_mes), ts, id_incidente)
) WITH CLUSTERING ORDER BY (ts DESC, id_incidente ASC);
