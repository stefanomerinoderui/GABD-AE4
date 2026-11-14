-- =============================================================================
-- Datos maestros (DML de alta inicial). Se cargan en pg-centro y llegan a las
-- sucursales por replicación lógica.
-- =============================================================================

INSERT INTO sucursales (id, nombre, region, provincia, ciudad, lat, lon) VALUES
    (1,  'Depósito Salta',        'norte',  'Salta',            'Salta',                    -24.7859, -65.4117),
    (2,  'Depósito Tucumán',      'norte',  'Tucumán',          'San Miguel de Tucumán',    -26.8083, -65.2176),
    (3,  'Depósito Resistencia',  'norte',  'Chaco',            'Resistencia',              -27.4514, -58.9867),
    (4,  'Depósito Corrientes',   'norte',  'Corrientes',       'Corrientes',               -27.4692, -58.8306),
    (5,  'Depósito Posadas',      'norte',  'Misiones',         'Posadas',                  -27.3671, -55.8961),
    (6,  'Sede Central',          'centro', 'Buenos Aires',     'Ciudad de Buenos Aires',   -34.6037, -58.3816),
    (7,  'Depósito Córdoba',      'centro', 'Córdoba',          'Córdoba',                  -31.4201, -64.1888),
    (8,  'Depósito Rosario',      'centro', 'Santa Fe',         'Rosario',                  -32.9442, -60.6505),
    (9,  'Depósito Mendoza',      'centro', 'Mendoza',          'Mendoza',                  -32.8895, -68.8458),
    (10, 'Depósito Paraná',       'centro', 'Entre Ríos',       'Paraná',                   -31.7413, -60.5115),
    (11, 'Depósito Neuquén',      'sur',    'Neuquén',          'Neuquén',                  -38.9516, -68.0591),
    (12, 'Depósito Bahía Blanca', 'sur',    'Buenos Aires',     'Bahía Blanca',             -38.7183, -62.2663),
    (13, 'Depósito Comodoro',     'sur',    'Chubut',           'Comodoro Rivadavia',       -45.8641, -67.4966),
    (14, 'Depósito Bariloche',    'sur',    'Río Negro',        'San Carlos de Bariloche',  -41.1335, -71.3103),
    (15, 'Depósito Ushuaia',      'sur',    'Tierra del Fuego', 'Ushuaia',                  -54.8019, -68.3030);

-- Flota: 4 vehículos por sucursal (60 en total), alternando tipos.
INSERT INTO vehiculos (id, patente, tipo, capacidad_kg, sucursal_base_id)
SELECT
    n,
    'LF' || lpad(n::text, 3, '0') || 'AR',
    (ARRAY['utilitario', 'camion', 'camion_refrigerado'])[1 + n % 3],
    (ARRAY[1200, 12000, 9000])[1 + n % 3],
    1 + (n - 1) % 15
FROM generate_series(1, 60) AS n;
