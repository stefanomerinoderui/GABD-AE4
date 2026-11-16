-- Conexión: Central (pg-centro)
-- Fase 3: planes de ejecución sobre los fragmentos. Los índices se crean con
-- `python tareas.py` / notebook 03; si no existen, el plan usa Seq Scan.

-- 1. Índices existentes del fragmento local.
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'envios_centro' ORDER BY 1;

-- 2. Envíos recientes de un cliente (B-tree compuesto cliente_id, fecha_alta).
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, estado, fecha_alta FROM envios_centro
WHERE cliente_id = 1 ORDER BY fecha_alta DESC LIMIT 20;

-- 3. Envíos abiertos por sucursal (índice parcial).
EXPLAIN (ANALYZE, BUFFERS)
SELECT sucursal_destino_id, count(*) FROM envios_centro
WHERE estado IN ('pendiente', 'en_transito') GROUP BY 1;

-- 4. Rango de fechas (BRIN sobre fecha_alta).
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM envios_centro
WHERE fecha_alta >= '2026-01-01' AND fecha_alta < '2026-02-01';

-- 5. Tamaño de los índices.
SELECT indexrelid::regclass AS indice, pg_size_pretty(pg_relation_size(indexrelid)) AS tamano
FROM pg_index WHERE indrelid = 'envios_centro'::regclass;

-- 6. Agregación directa sobre los tres fragmentos vs. lectura de la vista materializada.
EXPLAIN (ANALYZE, BUFFERS)
SELECT region, date_trunc('month', fecha_alta AT TIME ZONE 'UTC')::date AS mes, count(*)
FROM envios GROUP BY 1, 2;

EXPLAIN (ANALYZE, BUFFERS)
SELECT region, mes, total_envios FROM resumen_envios_mensual;
