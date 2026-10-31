# Desplegar On Air con Docker Compose y Caddy en el host

Esta guía usa el Caddy que ya está instalado y ejecutándose directamente en el servidor. Docker Compose levanta la web y la API; la web queda publicada solo en `127.0.0.1:8080`. Caddy termina HTTPS y reenvía las solicitudes al contenedor web. Nginx, dentro de ese contenedor, sirve Svelte y pasa `/api` al backend. SQLite persiste en el volumen `onair-data`.

```text
Internet ── HTTPS ── Caddy (host) ── 127.0.0.1:8080 ── Nginx/web ──┬── Svelte
                                                                    └── API ── SQLite
```

## 1. Requisitos

- Servidor Linux con Docker Engine y el plugin Docker Compose.
- Caddy instalado en el host y funcionando como servicio.
- Dominio (por ejemplo `tv.midominio.com`) con DNS `A` (y `AAAA` si aplica) apuntando a la IP pública del servidor.
- TCP `80` y `443` accesibles desde Internet para que Caddy obtenga y renueve TLS. La emisión automática de certificados requiere un hostname público resoluble y que Caddy pueda atender esos puertos ([requisitos de Caddy](https://caddyserver.com/docs/automatic-https)).

No agregues otro Caddy en Docker ni publiques al exterior el puerto de Nginx o el de la API. El Compose de este proyecto enlaza la web únicamente a loopback.

## 2. Obtener el proyecto y configurar Compose

```sh
sudo mkdir -p /opt/on-air
sudo chown "$USER":"$USER" /opt/on-air
cd /opt/on-air
git clone <URL_DEL_REPOSITORIO> .
cp .env.example .env
```

El `.env` debe contener los orígenes permitidos para las apps Tauri y el puerto local de la web:

```dotenv
CORS_ORIGINS=tauri://localhost,https://tauri.localhost
WEB_PORT=8080
VITE_API_BASE_URL=
```

La web llama a la API en el mismo origen; CORS se usa para las apps de escritorio. La API publica lectura únicamente y no requiere cuentas.

Valida y arranca los contenedores:

```sh
docker compose config
docker compose up -d --build
docker compose ps
```

Comprueba desde el propio servidor que el puerto está escuchando en loopback y que la API responde a través de Nginx:

```sh
curl -I http://127.0.0.1:8080/
curl http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/api/v1/status
```

El catálogo se importa al iniciar el backend y luego cada 12 horas. La guía XMLTV se carga cuando un cliente solicita por primera vez un país durante el día UTC; el servidor comparte esa guía hasta que cambia el día.

## 3. Añadir el sitio al Caddy del host

Edita el Caddyfile que ya usa el servicio instalado. En instalaciones Linux comunes está en `/etc/caddy/Caddyfile`; si tu servicio usa otra ruta, modifica el archivo configurado en ese servicio. **Conserva los sitios existentes** y añade este bloque cambiando el hostname:

```caddyfile
tv.midominio.com {
  encode zstd gzip
  reverse_proxy 127.0.0.1:8080
}
```

Valida y recarga Caddy:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Si el Caddy del host se gestiona de otra manera, usa el mecanismo de validación y recarga correspondiente a esa instalación. Caddy redirige HTTP a HTTPS y gestiona la emisión y renovación del certificado cuando el dominio resuelve al servidor y los puertos requeridos están accesibles ([documentación de reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)).

Verifica desde el servidor y desde una máquina externa:

```sh
curl -I https://tv.midominio.com/
curl https://tv.midominio.com/health
curl -sS https://tv.midominio.com/api/v1/status
curl -sS 'https://tv.midominio.com/api/v1/guides?country=PE' | head -c 500
```

La primera solicitud de una guía puede tardar mientras descarga y procesa XMLTV.

## 4. Compilar la app de escritorio

Apunta el build de Tauri al origen público del sitio, sin `/api` al final:

```sh
VITE_API_BASE_URL=https://tv.midominio.com npm run tauri build
```

Asegúrate de que `CORS_ORIGINS` incluya el origen Tauri correspondiente. El sitio web usa la ruta relativa `/api` por el mismo host.

## 5. Actualizar la instalación

Haz una copia de SQLite antes de actualizar y ejecuta:

```sh
cd /opt/on-air
git pull --ff-only
docker compose up -d --build
docker compose ps
curl -fsS https://tv.midominio.com/health
```

Compose recrea los servicios y conserva el volumen nombrado. Para volver al código anterior, selecciona el commit previo y repite `docker compose up -d --build`. No elimines el volumen durante el rollback.

## 6. Respaldar la base SQLite

Este comando usa la API de backup de SQLite para copiar correctamente la base aunque esté usando WAL:

```sh
BACKUP="on-air-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
docker compose exec -T backend python -c 'import sqlite3; s=sqlite3.connect("/data/on-air.sqlite3"); d=sqlite3.connect("/tmp/on-air-backup.sqlite3"); s.backup(d); d.close(); s.close()'
docker cp "$(docker compose ps -q backend):/tmp/on-air-backup.sqlite3" "$BACKUP"
```

Guarda el archivo fuera del servidor o en almacenamiento de backups protegido, con una política de retención. Prueba periódicamente una restauración. La configuración y los datos TLS de Caddy pertenecen al host; respalda también el directorio de datos que usa el servicio Caddy si necesitas conservar ese estado.

`docker compose down` conserva los volúmenes. Evita `docker compose down -v`, porque elimina el volumen que contiene el catálogo y las guías.

## 7. Operación y diagnóstico

```sh
docker compose ps
docker compose logs -f web backend
sudo journalctl -u caddy -f
```

- **No aparece HTTPS:** revisa DNS, acceso entrante a TCP 80/443 y `journalctl -u caddy`.
- **Caddy devuelve 502:** verifica `docker compose ps` y `curl http://127.0.0.1:8080/health` en el host.
- **Catálogo vacío o antiguo:** revisa los logs del backend y `https://tv.midominio.com/api/v1/status`. El backend conserva la última copia válida si IPTV-org no responde.
- **Guía no disponible:** comprueba los logs del backend y la disponibilidad de ese país en IPTV-EPG; se puede reintentar si no se guardó una copia válida ese día.
- **Disco lleno:** vigila el volumen Docker y el espacio destinado a backups.
