-- Conexión: Data warehouse (pg-dw)
-- Constelación de hechos: hechos_entregas y hechos_incidentes.

-- 1. Slice: entregas del año 2026 por región de origen.
SELECT g.region, count(*) AS entregas, round(avg(h.horas_entrega), 1) AS horas_prom
FROM hechos_entregas h
JOIN dim_geografia g ON g.geografia_id = h.geografia_origen_id
JOIN dim_tiempo t ON t.tiempo_id = h.tiempo_id
WHERE t.anio = 2026
GROUP BY g.region ORDER BY 1;

-- 2. ROLLUP: región > provincia con subtotales.
SELECT g.region, g.provincia, count(*) AS entregas
FROM hechos_entregas h
JOIN dim_geografia g ON g.geografia_id = h.geografia_origen_id
GROUP BY ROLLUP (g.region, g.provincia) ORDER BY 1, 2;

-- 3. CUBE: región x año.
SELECT g.region, t.anio, count(*) AS entregas
FROM hechos_entregas h
JOIN dim_geografia g ON g.geografia_id = h.geografia_origen_id
JOIN dim_tiempo t ON t.tiempo_id = h.tiempo_id
GROUP BY CUBE (g.region, t.anio) ORDER BY 1, 2;

-- 4. Comparación interanual del tiempo de entrega por región (mejora del Sur en 2026).
SELECT g.region,
       round(avg(h.horas_entrega) FILTER (WHERE t.anio = 2025), 1) AS horas_2025,
       round(avg(h.horas_entrega) FILTER (WHERE t.anio = 2026), 1) AS horas_2026
FROM hechos_entregas h
JOIN dim_geografia g ON g.geografia_id = h.geografia_origen_id
JOIN dim_tiempo t ON t.tiempo_id = h.tiempo_id
GROUP BY g.region ORDER BY 1;

-- 5. Drill-across: incidentes y demora por región (segunda tabla de hechos, dimensiones conformadas).
SELECT g.region, i.tipo, count(*) AS incidentes, round(avg(i.demora_min)) AS demora_min_prom
FROM hechos_incidentes i
JOIN dim_geografia g ON g.geografia_id = i.geografia_id
GROUP BY g.region, i.tipo ORDER BY 1, 3 DESC;

-- 6. Particionamiento por rango: filas por partición y poda por año.
SELECT tableoid::regclass AS particion, count(*) AS filas
FROM hechos_entregas GROUP BY 1 ORDER BY 1;

EXPLAIN SELECT * FROM hechos_entregas WHERE tiempo_id BETWEEN 20260101 AND 20261231;
