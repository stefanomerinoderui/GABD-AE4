-- =============================================================================
-- Índices físicos estratégicos. Se aplican DESPUÉS de cargar datos
-- (src/logistica/indices.py) para poder comparar los planes antes y después.
-- Plantilla (no es psql directo): src/logistica/indices.py reemplaza {tabla} por el
-- fragmento de Envios sobre el que se crean los índices.
--
-- Criterio: cada índice responde a una consulta concreta y frecuente; se evita
-- indexar columnas de baja selectividad que solo encarecerían las escrituras.
-- =============================================================================

-- "Envíos de un cliente, los más recientes primero" (portal de clientes).
CREATE INDEX IF NOT EXISTS {tabla}_cliente_fecha ON {tabla} (cliente_id, fecha_alta DESC);

-- Panel operativo: solo los envíos abiertos (<5 % de la tabla). Índice parcial:
-- ocupa poco y no se actualiza cuando un envío ya cerrado cambia.
CREATE INDEX IF NOT EXISTS {tabla}_abiertos ON {tabla} (sucursal_destino_id, fecha_alta)
    WHERE estado IN ('pendiente', 'en_transito');

-- Reportes por rango de fechas. La tabla es append-only y fecha_alta crece con
-- la inserción: BRIN guarda un resumen por rango de páginas (KB frente a MB de
-- un B-tree) con muy poco costo de escritura.
CREATE INDEX IF NOT EXISTS {tabla}_fecha_brin ON {tabla} USING brin (fecha_alta);
