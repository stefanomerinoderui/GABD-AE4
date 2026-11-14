# Caso de Estudio: Sistema de Logística y Trazabilidad de Envíos ("Logística Federal")

## 1. Contexto del Negocio y Justificación de la Distribución
**"Logística Federal"** es una empresa de transporte de paquetería con alcance nacional, estructurada en tres grandes nodos operativos: Norte, Centro y Sur. 

El sistema centralizado anterior presentaba graves cuellos de botella:
* **Latencia:** Los depósitos del Sur experimentaban demoras al registrar el ingreso de paquetes porque consultaban al servidor en la sede Central.
* **Disponibilidad (Punto único de fallo):** Si se cortaba el enlace de fibra óptica en la sede Central, los camiones de todo el país no podían despachar la mercadería.
* **Volumen de datos heterogéneos:** El sistema debe procesar transacciones estructuradas (pagos, remitos) y un volumen masivo de datos no estructurados (coordenadas GPS de los camiones, logs de sensores IoT de temperatura en la carga).

**Justificación Tecnológica:** Se requiere una Base de Datos Distribuida (BDD) para garantizar la autonomía local (cada sucursal debe poder seguir operando sin conexión a la central) y escalar horizontalmente para soportar el flujo masivo de eventos de rastreo (tracking).

---

## 2. Fase 1: Arquitectura de Almacenamiento Distribuido (Diseño Lógico)

Para abordar la heterogeneidad de los datos, se propone un modelo de **Persistencia Políglota** (híbrido):

### A. Subsistema Relacional (Gestión Comercial y Operativa)
Utilizado para clientes, facturación y catálogo de sucursales (ej. PostgreSQL distribuido).
* **Fragmentación Horizontal:** La tabla `Envios` se fragmenta por región. El nodo Norte almacena solo los envíos con origen/destino en su región. Esto cumple las reglas de *completitud, reconstrucción y disyunción*, agilizando las consultas locales.
* **Fragmentación Vertical:** La tabla `Clientes` se fragmenta verticalmente. Los datos operativos (nombre, dirección) se replican en las sucursales, pero los datos sensibles (tarjetas de crédito, historial crediticio) permanecen exclusivamente fragmentados en el nodo de la Sede Central.
* **Replicación:** Se configura una replicación *sincrónica* estricta para las transacciones de facturación, garantizando propiedades ACID.

### B. Subsistema NoSQL (Trazabilidad y Tracking en Tiempo Real)
Utilizado para los eventos geolocalizados de los paquetes (ej. Apache Cassandra o MongoDB).
* **Diseño:** Modelo Columnar o de Familia de Columnas.
* **Distribución:** Particionamiento (Sharding) basado en el `ID_Paquete` o por ventanas de tiempo. 
* **Replicación:** Replicación *asincrónica* con consistencia eventual (Modelo BASE). Se prioriza la ingesta masiva de datos a altísima velocidad sobre la consistencia inmediata.

---

## 3. Fase 2: Resiliencia, Tolerancia a Fallas y Teorema CAP

### A. Teorema CAP en la Arquitectura
Ante una partición de red (caída del enlace entre el nodo Norte y la Central):
* **Para el Subsistema NoSQL (Tracking):** El diseño sacrifica la Consistencia fuerte a favor de la Disponibilidad (**AP** en el Teorema CAP). Los escáneres de los depósitos pueden seguir registrando los movimientos de los paquetes a nivel local. Una vez restablecida la red, los nodos sincronizan sus réplicas.
* **Para el Subsistema Relacional (Facturación):** El diseño sacrifica la Disponibilidad a favor de la Consistencia (**CP**). No se permitirá procesar un pago distribuido si no hay quórum de nodos, para evitar desfasajes financieros.

### B. Gestor de Recuperación (Recuperación ante desastres)
Si el nodo Sur sufre un corte abrupto de energía, el motor relacional utilizará el protocolo de recuperación basado en el archivo **WAL (Write-Ahead Log)**:
* **UNDO (Deshacer):** Transacciones de alta de paquetes que no lograron registrar un `COMMIT` antes del apagón serán revertidas leyendo el log.
* **REDO (Rehacer):** Transacciones que hicieron `COMMIT` pero cuyos bloques de datos aún estaban en la memoria intermedia (Buffer) serán reconstruidas usando el WAL para garantizar la **Durabilidad**.

### C. Políticas de Respaldo
* **RTO (Tiempo Objetivo de Recuperación):** 2 horas máximo de inactividad operativa.
* **RPO (Punto Objetivo de Recuperación):** 15 minutos (se asume pérdida máxima de los últimos 15 minutos de tracking).
* **Estrategia:** Backups completos semanales y copias incrementales cada hora, con envío asíncrono a almacenamiento en la nube (Cold Storage).

---

## 4. Fase 3: Analítica y Minería de Datos (KDD)

Para extraer valor estratégico de los datos de logística generados por la BDD, se implementará un entorno de explotación analítica:

### A. Modelado Multidimensional (Data Warehouse / OLAP)
* **Modelo:** Esquema de Constelación de Hechos (Fact Constellation).
* **Tablas de Hechos:** `Hechos_Entregas` y `Hechos_Incidentes`.
* **Dimensiones Compartidas:** `Tiempo` (Día, Mes, Año), `Geografía` (Región, Provincia, Ciudad), `Vehículo`.
* **Objetivo:** Permitir operaciones de *Slicing and Dicing* para responder preguntas críticas de negocio, como el promedio de tiempo de entrega por región comparando el año actual con el anterior.

### B. Minería de Datos Espaciales y Predictivos
Siguiendo las fases de la metodología **CRISP-DM / KDD**:
1. **Modelado Predictivo (Regresión):** Aplicación de algoritmos de regresión lineal o redes neuronales recurrentes (RNN/LSTM) para analizar series temporales y calcular el ETA (Tiempo Estimado de Llegada) basándose en tráfico histórico y clima.
2. **Modelado Descriptivo (Clustering / Espacial):** Aplicación de algoritmos como **DBSCAN** o **K-Means** sobre los datos de GPS. Al agrupar (clusterizar) las zonas con mayor densidad de retrasos o incidentes (puntos calientes), la empresa puede redistribuir sus rutas de reparto u optimizar la ubicación de futuros centros de transferencia (*Edge Computing*).