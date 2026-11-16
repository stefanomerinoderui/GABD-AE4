-- Conexión: Central (pg-centro)
-- Vista materializada resumen_envios_mensual (envíos por región y mes).

-- 1. Resumen completo, mes a mes.
SELECT * FROM resumen_envios_mensual ORDER BY mes, region;

-- 2. Totales por región.
SELECT region,
       sum(total_envios)  AS envios,
       sum(entregados)    AS entregados,
       sum(cancelados)    AS cancelados,
       sum(abiertos)      AS abiertos,
       round(sum(peso_total_kg), 1) AS peso_kg
FROM resumen_envios_mensual
GROUP BY region
ORDER BY region;

-- 3. Estado de la vista (poblada) y su índice único, requisito de CONCURRENTLY.
SELECT matviewname, ispopulated FROM pg_matviews WHERE matviewname = 'resumen_envios_mensual';
SELECT indexdef FROM pg_indexes WHERE indexname = 'resumen_envios_mensual_pk';

-- 4. Refresco sin bloquear a los lectores (ejecutar en modo script, Alt+X;
--    en DBeaver con auto-commit activado).
REFRESH MATERIALIZED VIEW CONCURRENTLY resumen_envios_mensual;

-- 5. Control: la vista coincide con la agregación directa (debe devolver 0 filas).
SELECT region, count(*) AS directo FROM envios GROUP BY region
EXCEPT
SELECT region, sum(total_envios)::bigint FROM resumen_envios_mensual GROUP BY region;
