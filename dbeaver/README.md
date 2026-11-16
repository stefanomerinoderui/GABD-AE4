# Proyecto DBeaver · Logística Federal

Conexiones y scripts SQL listos para explorar y presentar el clúster con
[DBeaver](https://dbeaver.io/) (Community alcanza). Cassandra no está incluida: DBeaver Community
no la soporta; use el notebook `02` o `cqlsh` (`docker compose exec cassandra-centro cqlsh`).

## Requisitos

1. Clúster levantado con datos: `python tareas.py up` y `python tareas.py seed`.
   Si el clúster se creó antes de que existieran los puertos de Norte y Sur (5434/5435) o las
   particiones del DW, vuelva a ejecutar `python tareas.py up` (puertos) o `python tareas.py reset --si` (DW).
2. DBeaver instalado. Los puertos están publicados solo en `127.0.0.1`.

## Cargar conexiones y scripts

Esta carpeta es el contenido de un proyecto de DBeaver, no un archivo `.dbp` (el asistente
*Importar → DBeaver → Project* solo acepta ese formato). Se carga copiando los archivos al proyecto
`General` del workspace:

1. Cierre DBeaver.
2. Copie `dbeaver/.dbeaver/data-sources.json` a `<workspace>/General/.dbeaver/` (si ya tiene conexiones,
   no lo sobrescriba: abra ambos archivos y agregue las cuatro entradas de `connections`).
3. Copie `dbeaver/Scripts/*.sql` a `<workspace>/General/Scripts/`.
4. Abra DBeaver: aparece la carpeta de conexiones **Logística Federal** y los scripts en *Scripts*.

Ubicación del workspace según el sistema:

| Sistema | `<workspace>` |
|---|---|
| Linux | `~/.local/share/DBeaverData/workspace6` |
| Windows | `%APPDATA%\DBeaverData\workspace6` |
| macOS | `~/Library/DBeaverData/workspace6` |

(DBeaver instalado por Flatpak o Snap usa una ruta distinta; en *Archivo → Cambiar workspace* se ve la actual.)

Alternativa sin copiar nada: cree las cuatro conexiones a mano con la tabla de abajo (*Nueva conexión →
PostgreSQL*) y abra los scripts con *Archivo → Abrir archivo…*.

## Conexiones

| Conexión | Host:puerto | Base | Contenido |
|---|---|---|---|
| Central (pg-centro) | 127.0.0.1:5432 | `logistica` | `envios` (tabla particionada), catálogo, facturación, vista materializada |
| Norte (pg-norte) | 127.0.0.1:5434 | `logistica` | fragmento físico `envios_norte`, suscripción al catálogo |
| Sur (pg-sur) | 127.0.0.1:5435 | `logistica` | fragmento físico `envios_sur`, suscripción al catálogo |
| Data warehouse (pg-dw) | 127.0.0.1:5433 | `dw` | constelación de hechos y dimensiones |

Usuario: `logistica`. La contraseña no está en el proyecto: DBeaver la pide al conectar
(desarrollo local: `POSTGRES_PASSWORD` de su `.env`, por defecto `logistica_dev`).
Si cambió los puertos en `.env`, edite el puerto de la conexión.

## Scripts

Cada script indica en el primer comentario la conexión a usar. Seleccione la conexión
(*Ctrl+9* o el selector de la barra), ejecute una sentencia con **Ctrl+Enter** o todo el script con **Alt+X**.

| Script | Conexión | Para qué |
|---|---|---|
| `01_vista_resumen.sql` | Central | vista materializada, estado, `REFRESH … CONCURRENTLY` y control de consistencia |
| `02_fragmentacion.sql` | Central | fragmentación horizontal/vertical, poda de particiones, replicación síncrona y lógica |
| `03_indices_explain.sql` | Central | `EXPLAIN (ANALYZE, BUFFERS)` de B-tree, índice parcial y BRIN; vista vs. agregación directa |
| `04_olap.sql` | Data warehouse | slice, `ROLLUP`, `CUBE`, interanual, drill-across, particiones por rango |
| `05_resiliencia_cap.sql` | Central | rol del nodo, retraso del standby, WAL, archivado, commits en espera (`SyncRep`), 2PC |

Para el plan de ejecución gráfico: seleccione un `EXPLAIN` y use *Ctrl+Shift+E* (Explain Execution Plan).

## Para la presentación

* Diagramas ER: clic derecho sobre el esquema `public` → *View Diagram* (Central para la fragmentación; DW para
  la constelación) y *Save as image*.
* Resultados: en la grilla, *Export data* → CSV/XLSX (por ejemplo `resumen_envios_mensual`).
* Para mostrar el failover (`python tareas.py failover`) deje abierta `05_resiliencia_cap.sql` y vuelva a
  ejecutar las consultas 1 y 2; tras el failover `pg_is_in_recovery()` cambia de nodo (reconecte a `pg-centro-replica`
  si la conexión original cayó).
