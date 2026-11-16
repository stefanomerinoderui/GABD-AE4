-- =============================================================================
-- Vista materializada: resumen de envíos por región y mes (tablero gerencial).
--
-- Agrega sobre la tabla global "envios", por lo que lee también los fragmentos
-- foráneos (Norte/Sur). Precalcularla evita repetir ese recorrido distribuido
-- en cada consulta del tablero.
--
-- No se crea en el init de pg-centro: pg-norte y pg-sur se inicializan después
-- y la vista depende de ellos. Lo hace src/logistica/resumen.py (idempotente).
--
-- REFRESH ... CONCURRENTLY exige (1) un índice UNIQUE sobre columnas simples,
-- sin WHERE, y (2) que la vista ya esté poblada; por eso se crea WITH NO DATA y
-- la primera carga es un REFRESH normal.
-- =============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS resumen_envios_mensual AS
SELECT region,
       date_trunc('month', fecha_alta AT TIME ZONE 'UTC')::date AS mes,
       count(*)                                                  AS total_envios,
       count(*) FILTER (WHERE estado = 'entregado')              AS entregados,
       count(*) FILTER (WHERE estado = 'cancelado')              AS cancelados,
       count(*) FILTER (WHERE estado IN ('pendiente', 'en_transito')) AS abiertos,
       sum(peso_kg)                                              AS peso_total_kg,
       sum(distancia_km)                                         AS distancia_total_km,
       round(avg(extract(epoch FROM fecha_entrega - fecha_alta) / 3600)
             FILTER (WHERE estado = 'entregado'), 2)             AS horas_promedio_entrega
FROM envios
GROUP BY region, date_trunc('month', fecha_alta AT TIME ZONE 'UTC')
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS resumen_envios_mensual_pk
    ON resumen_envios_mensual (region, mes);
