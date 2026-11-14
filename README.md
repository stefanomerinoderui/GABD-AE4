# GABD-AE4 · Logística Federal — base de datos distribuida

Implementación práctica de la AE4 (Gestión Avanzada de Bases de Datos) para el caso de
[`sistema_de_logistica.md`](sistema_de_logistica.md), según los requerimientos de
[`estructura_base_y_requerimientos_ae4.md`](estructura_base_y_requerimientos_ae4.md).

Persistencia políglota sobre un clúster de 11 contenedores:

| Subsistema | Nodos | Teorema CAP | Replicación |
|---|---|---|---|
| **PostgreSQL 18** (clientes, envíos, facturación) | `pg-centro` (primario) · `pg-centro-replica` (standby) · `pg-norte` · `pg-sur` | **CP** | síncrona (Central → standby) y lógica asíncrona (catálogo → sucursales) |
| **Cassandra 5.0** (tracking, GPS, incidentes) | `cassandra-norte` · `-centro` · `-sur` (RF = 3) | **AP** | asíncrona, consistencia eventual (BASE) |
| **Analítica** | `pg-dw` (constelación de hechos) · `jupyter` | — | ETL batch |

## Requisitos

Solo **Docker (Compose v2)** y **Python ≥ 3.10**: toda la operación es Python estándar, sin `make`
ni bash en el host, por lo que funciona igual en Linux, macOS y Windows.

* Windows/macOS: Docker Desktop (en Windows, con el backend WSL 2). Linux: Docker Engine + plugin Compose.
* **~6 GB de RAM libres** para Docker (3 nodos Cassandra con heap de 512 MB + 5 PostgreSQL).
* Puertos libres en `127.0.0.1`: 5432, 5433, 9042, 8888 (configurables en `.env`).
* Opcional, para `lint`: `ruff` y `shellcheck`.

## Inicio rápido

```bash
python tareas.py up      # crea .env, construye imágenes y levanta todo (~3 min la primera vez)
python tareas.py seed    # datos sintéticos (semilla fija) + carga del data warehouse
python tareas.py test    # 41 tests (29 de integración contra el clúster + 12 unitarios)
```

En Windows use `py tareas.py ...` en lugar de `python tareas.py ...`. `python tareas.py` sin argumentos
lista todos los comandos.

JupyterLab: <http://127.0.0.1:8888/?token=logistica> (el token está en `.env`). Los notebooks se
ejecutan en orden `01` → `05`; `python tareas.py notebooks` los corre todos de punta a punta.
`python tareas.py reset` destruye todo y reconstruye desde cero (prueba de reproducibilidad).

## Mapa de requerimientos → código

### Fase 1 · Almacenamiento distribuido y ABM — [`notebooks/01_fragmentacion_y_abm.ipynb`](notebooks/01_fragmentacion_y_abm.ipynb)

| Requerimiento | Implementación |
|---|---|
| Fragmentación **horizontal** | `envios`: tabla particionada por lista (`region`) en `pg-centro`; las particiones `norte`/`sur` son tablas foráneas (`postgres_fdw`) hacia la tabla física de cada sucursal — [`postgres/centro/02_fragmentacion.sql`](postgres/centro/02_fragmentacion.sql). Completitud, disyunción y reconstrucción se verifican en el notebook y en `tests/test_fragmentacion.py`. |
| Fragmentación **vertical** | `clientes` = `clientes_operativo` (replicado a sucursales) + `clientes_sensible` (solo Central), reunidos por la vista `clientes` — [`postgres/centro/01_esquema.sql`](postgres/centro/01_esquema.sql). |
| Replicación **síncrona** | `synchronous_standby_names = 'ANY 1 (...)'` + `synchronous_commit = remote_apply` — [`postgres/centro/04_replicacion.sql`](postgres/centro/04_replicacion.sql). |
| Replicación **asíncrona** | Lógica parcial (publication/subscription) del catálogo; Cassandra RF = 3 — [`postgres/regional/02_suscripcion.sql`](postgres/regional/02_suscripcion.sql), [`cassandra/01_keyspace_tablas.cql`](cassandra/01_keyspace_tablas.cql). |
| ABM consistente | [`src/logistica/abm.py`](src/logistica/abm.py): cada operación va al nodo dueño; las que cruzan nodos (envío + factura) usan **two-phase commit**. Tracking en [`tracking.py`](src/logistica/tracking.py). |

Decisiones de diseño: UUID v7 como clave de envíos (cada nodo genera ids sin coordinarse y el índice
conserva el orden temporal); sin FK de envíos a clientes (el catálogo llega asíncrono y una FK
rechazaría clientes recién creados — valida el ABM); tablas de Cassandra una por patrón de consulta,
con ventanas de tiempo para acotar el tamaño de las particiones.

### Fase 2 · Resiliencia — [`notebooks/02_resiliencia_cap.ipynb`](notebooks/02_resiliencia_cap.ipynb)

| Escenario | Comando | Resultado esperado |
|---|---|---|
| Corte de energía en Sur (WAL: REDO/UNDO) | `python tareas.py recuperacion-wal` | El commit sobrevive (REDO); la transacción abierta desaparece (UNDO). Muestra el log de recuperación. |
| Caída de un nodo Cassandra | `python tareas.py caida-cassandra` | `ONE`/`QUORUM` siguen escribiendo; `ALL` falla; tras `nodetool repair` los datos convergen. |
| Partición del Norte | `python tareas.py particion-red` | El Norte sigue despachando (autonomía); Central no puede leer ese fragmento (CP); el evento de tracking aparece en Central tras reconectar (AP). |
| Caída del primario de Central | `python tareas.py failover` | Promoción del standby con **cero pérdida**; sin standby síncrono los COMMIT esperan (`SyncRep`). |
| Volver a la normalidad | `python tareas.py reincorporar` | `pg_rewind` del antiguo primario, que vuelve como standby síncrono (roles invertidos). Alternativa de emergencia: `python tareas.py failover --degradado`. |

**CAP, coherente con el caso:** facturación = **CP** (sin quórum no se confirma un pago); tracking =
**AP** (el escáner de un depósito aislado sigue registrando; las réplicas se reconcilian después).
Nota técnica: en PostgreSQL la espera de `synchronous_commit` ocurre *después* del commit local —
lo que se bloquea es la confirmación al cliente; el script de failover limpia el registro de prueba.

**Backups (RPO 15 min · RTO 2 h)** — destino: volumen `backups` (simula el almacenamiento frío; hay una línea
comentada de `aws s3 sync` en [`operaciones/programacion.md`](operaciones/programacion.md) (cron y Programador de tareas de Windows)).

| Pieza | Script / ajuste | Aporta |
|---|---|---|
| Archivado continuo de WAL | `archive_mode=on`, `archive_timeout=900` ([`postgres/conf/20-archivado.conf`](postgres/conf/20-archivado.conf)) | **RPO ≤ 15 min** |
| Completo semanal | `python tareas.py backup` | punto de partida de la restauración |
| Incremental horario | `python tareas.py backup-incremental` | reduce ventana y volumen |
| Restauración PITR | `python tareas.py restore --instante "2026-11-14 21:58:16+00"` (limpiar: `python tareas.py restore-limpiar`) | `pg_combinebackup` + WAL; imprime el **RTO** medido |
| Cassandra | `python tareas.py backup-cassandra` | snapshots + backups incrementales de SSTables |

El RTO real depende del volumen; el script lo mide (segundos en este laboratorio). Para una base real,
el tiempo se estima como copia del completo + combinación de incrementales + reproducción del WAL
(a lo sumo ~1 h de WAL con incrementales horarios) y debe quedar por debajo de las 2 h.

### Fase 3 · Tuning y analítica

| Tema | Dónde |
|---|---|
| Índices y `EXPLAIN (ANALYZE, BUFFERS)` | [`03_indices_explain.ipynb`](notebooks/03_indices_explain.ipynb) · [`postgres/comun/03_indices.sql`](postgres/comun/03_indices.sql) · [`indices.py`](src/logistica/indices.py): B-tree compuesto, índice parcial y BRIN; mejora de lecturas ×10–×300 y sobrecosto de escritura medido. |
| OLAP: constelación de hechos | [`04_olap.ipynb`](notebooks/04_olap.ipynb) · [`postgres/dw/01_constelacion.sql`](postgres/dw/01_constelacion.sql) · [`etl.py`](src/logistica/etl.py): slice, dice, `ROLLUP`, `CUBE`, comparación interanual y drill-across. |
| Minería (CRISP-DM) | [`05_mineria_kdd.ipynb`](notebooks/05_mineria_kdd.ipynb) · [`mineria.py`](src/logistica/mineria.py): regresión lineal para ETA, DBSCAN (haversine) y K-Means sobre incidentes. |

Los datos sintéticos incluyen señal deliberada (zonas críticas, mejora de la región Sur en 2026) para
que cada análisis tenga una respuesta verificable.

## Estructura

```
compose.yaml  tareas.py  .env.example  pyproject.toml
docker/       imágenes de PostgreSQL (standby) y Jupyter
postgres/     comun/ (catálogo, envíos, índices) · centro/ · regional/ · dw/ · conf/
cassandra/    keyspace y tablas CQL
src/logistica/  config · conexiones · abm · tracking · semilla · etl · mineria · indices
notebooks/    01 … 05 (sin salidas guardadas)
operaciones/  failover, particiones, backups, restauración, demos de recuperación (Python)
tareas.py     punto de entrada: `python tareas.py <comando>`
tests/        integración contra el clúster
```

## Operación y resolución de problemas

* `python tareas.py` lista todos los comandos (`--debug` muestra el traceback); `docker compose logs -f <servicio>` para depurar.
* Si un puerto está ocupado, cámbielo en `.env` y repita `python tareas.py up`.
* Cassandra tarda ~1 min en estar sana y los nodos arrancan en cadena (un nodo nuevo por vez es un requisito del anillo).
* Tras `python tareas.py failover` los roles quedan invertidos hasta `python tareas.py reincorporar`; los clientes Python no necesitan
  cambios porque listan ambos hosts con `target_session_attrs=read-write`.
* `python tareas.py lint` ejecuta `ruff` y `shellcheck` (si están instalados) y valida `compose.yaml`. Las credenciales de `.env.example` son solo para uso académico local.
