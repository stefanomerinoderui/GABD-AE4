# Programación de backups (RPO 15 min · RTO 2 h)

Política: **completo** semanal, **incremental** horario, **Cassandra** snapshot diario; el WAL se
archiva solo (`archive_timeout = 900`). Reemplace `RUTA` por la carpeta del repositorio.

## Linux / macOS (cron) — `crontab -e`

```cron
# Completo: domingos 02:00
0 2 * * 0     cd RUTA && python3 tareas.py backup
# Incremental: cada hora, salvo el momento del completo
0 * * * 1-6   cd RUTA && python3 tareas.py backup-incremental
0 3-23 * * 0  cd RUTA && python3 tareas.py backup-incremental
# Cassandra: snapshot diario
30 2 * * *    cd RUTA && python3 tareas.py backup-cassandra
```

## Windows (Programador de tareas)

```bat
schtasks /Create /TN "LF Backup completo"     /SC WEEKLY /D SUN /ST 02:00 /TR "cmd /c cd /d RUTA && py tareas.py backup"
schtasks /Create /TN "LF Backup incremental"  /SC HOURLY /TR "cmd /c cd /d RUTA && py tareas.py backup-incremental"
schtasks /Create /TN "LF Backup Cassandra"    /SC DAILY /ST 02:30 /TR "cmd /c cd /d RUTA && py tareas.py backup-cassandra"
```

## Envío al almacenamiento frío

Los backups quedan en el volumen Docker `logistica-federal_backups`. Para sincronizarlos con un
bucket (ejemplo con AWS CLI, ejecutable desde cualquier sistema con Docker):

```bash
docker run --rm -v logistica-federal_backups:/backups:ro -v ~/.aws:/root/.aws \
  amazon/aws-cli s3 sync /backups s3://BUCKET/logistica-federal --storage-class GLACIER
```
