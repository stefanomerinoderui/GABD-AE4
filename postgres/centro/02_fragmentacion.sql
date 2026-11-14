-- =============================================================================
-- Fragmentación horizontal de Envios por región (fragmentación primaria por
-- el predicado region = 'norte' | 'centro' | 'sur').
--
-- La tabla global "envios" es una tabla particionada por lista:
--   * envios_centro  partición local (el fragmento de esta sede)
--   * envios_norte   tabla foránea -> tabla física en pg-norte
--   * envios_sur     tabla foránea -> tabla física en pg-sur
--
-- Reglas de corrección:
--   Completitud     todo valor admitido de region tiene exactamente una partición
--                   (y no hay partición DEFAULT que esconda filas huérfanas).
--   Disyunción      las listas son excluyentes y cada fragmento físico tiene un
--                   CHECK (region = '<su región>').
--   Reconstrucción  SELECT sobre "envios" = UNION ALL de los tres fragmentos.
--
-- Variables psql: :usuario, :clave, :base (credenciales de los nodos remotos).
-- =============================================================================

CREATE EXTENSION postgres_fdw;

-- use_remote_estimate: el planificador pide estadísticas al nodo remoto.
-- async_capable: los fragmentos remotos se leen en paralelo en un Append.
CREATE SERVER srv_norte FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'pg-norte', port '5432', dbname :'base',
             use_remote_estimate 'true', async_capable 'true', fetch_size '5000');
CREATE SERVER srv_sur FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'pg-sur', port '5432', dbname :'base',
             use_remote_estimate 'true', async_capable 'true', fetch_size '5000');

CREATE USER MAPPING FOR CURRENT_USER SERVER srv_norte
    OPTIONS (user :'usuario', password :'clave');
CREATE USER MAPPING FOR CURRENT_USER SERVER srv_sur
    OPTIONS (user :'usuario', password :'clave');

CREATE TABLE envios_centro PARTITION OF envios FOR VALUES IN ('centro');
-- Una tabla particionada con particiones foráneas no admite PK global:
-- la unicidad se declara en cada fragmento físico.
ALTER TABLE envios_centro ADD PRIMARY KEY (id);

CREATE FOREIGN TABLE envios_norte PARTITION OF envios FOR VALUES IN ('norte')
    SERVER srv_norte OPTIONS (table_name 'envios_norte');
CREATE FOREIGN TABLE envios_sur PARTITION OF envios FOR VALUES IN ('sur')
    SERVER srv_sur OPTIONS (table_name 'envios_sur');
