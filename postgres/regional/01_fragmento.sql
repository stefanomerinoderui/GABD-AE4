-- =============================================================================
-- Fragmento horizontal local de Envios. Variables psql: :tabla, :region
-- =============================================================================

ALTER TABLE :"tabla" ADD PRIMARY KEY (id);

-- Disyunción: este nodo rechaza cualquier fila que pertenezca a otra región,
-- llegue por la tabla global de pg-centro o por una conexión directa.
ALTER TABLE :"tabla" ADD CONSTRAINT region_del_fragmento CHECK (region = :'region');
ALTER TABLE :"tabla" ALTER COLUMN region SET DEFAULT :'region';
