FROM postgres:18

# /backups: su dueño se hereda al volumen compartido (simula el cold storage).
# conf.d: permite montar la configuración común sin reemplazar postgresql.conf.
RUN mkdir -p /backups /etc/postgresql/conf.d \
    && chown postgres:postgres /backups \
    && echo "include_dir = '/etc/postgresql/conf.d'" >> /usr/share/postgresql/postgresql.conf.sample

COPY --chmod=755 configurar_standby.sh /usr/local/bin/configurar_standby
COPY --chmod=755 iniciar_standby.sh /usr/local/bin/iniciar_standby
