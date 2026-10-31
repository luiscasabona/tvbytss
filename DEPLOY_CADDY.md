# Desplegar On Air con Docker Compose y Caddy

Esta guía despliega la app web, la API y Caddy en un único servidor Linux. Caddy recibe el tráfico público, obtiene y renueva HTTPS automáticamente y reenvía a la web. Nginx, dentro del contenedor web, sirve los archivos estáticos y pasa `/api` al backend. La API y la web no publican puertos directamente al host; el volumen `onair-data` conserva SQLite.

```text
Internet ── HTTPS ── Caddy :443 ── web/nginx :80 ──┬── archivos Svelte
                                                   └── backend :8000 ── SQLite
```

## 1. Requisitos del servidor

- Servidor Linux con Docker Engine y el plugin Docker Compose instalados.
- Un dominio, por ejemplo `tv.midominio.com`, con los registros DNS `A` (y `AAAA` si el servidor tiene IPv6) apuntando a la IP pública del servidor.
- Puertos TCP `80` y `443` abiertos tanto en el firewall del servidor como en el firewall del proveedor. Se publica también UDP `443` para HTTP/3.
- El dominio debe resolver al servidor antes de arrancar Caddy. Caddy usa el nombre del sitio para solicitar y renovar el certificado automáticamente. [Requisitos de HTTPS automático de Caddy](https://caddyserver.com/docs/automatic-https).

Si hay otro servidor web usando esos puertos, hay que detenerlo o integrarlo como proxy externo. No se deben publicar directamente los puertos de Nginx o de la API.

## 2. Obtener el proyecto y configurar el dominio

En el servidor:

```sh
sudo mkdir -p /opt/on-air
sudo chown "$USER":"$USER" /opt/on-air
cd /opt/on-air
git clone <URL_DEL_REPOSITORIO> .
cp .env.example .env
```

Edita `.env` y configura el dominio real y los orígenes permitidos para las apps de escritorio:

```dotenv
DOMAIN=tv.midominio.com
CORS_ORIGINS=tauri://localhost,https://tauri.localhost
VITE_API_BASE_URL=
```

`CORS_ORIGINS` corresponde a macOS/Linux y Windows con Tauri. La web usa el mismo origen para llamar a la API. La API no tiene operaciones de escritura públicas ni cuentas de usuario. Mantén `.env` fuera del repositorio; contiene configuración del servidor.

## 3. Validar configuración e iniciar

Desde `/opt/on-air`:

```sh
docker compose config
docker compose up -d --build
```

El primer build descarga imágenes y dependencias, por lo que puede tardar. El backend importa el catálogo de IPTV-org al arrancar y luego cada 12 horas. La guía IPTV-EPG se importa la primera vez que se solicita cada país durante el día UTC; después se sirve la copia compartida guardada en SQLite.

Comprueba los contenedores y los logs:

```sh
docker compose ps
docker compose logs --tail=100 caddy web backend
```

Cuando Caddy haya obtenido el certificado, verifica el sitio y la API:

```sh
curl -I https://tv.midominio.com/
curl https://tv.midominio.com/health
curl -sS https://tv.midominio.com/api/v1/status
curl -sS 'https://tv.midominio.com/api/v1/guides?country=PE' | head -c 500
```

El endpoint de guía puede tardar en la primera solicitud del país mientras descarga y procesa XMLTV. La interfaz indica error si la fuente falla y permite reintentar. Revisa `docker compose logs -f caddy backend` si el certificado o la importación no avanzan.

## 4. Compilar la app de escritorio

La versión web usa la ruta relativa `/api` a través de Nginx. Para compilar una versión de Tauri que consuma el servidor, define la URL pública de la API al ejecutar el build:

```sh
VITE_API_BASE_URL=https://tv.midominio.com npm run tauri build
```

El valor debe ser el origen del sitio, sin `/api` al final. El servidor deberá permitir los orígenes Tauri de la plataforma en `CORS_ORIGINS`.

## 5. Actualizar la instalación

Antes de actualizar, crea una copia de seguridad como se describe abajo. Después, desde la carpeta del proyecto:

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Compose recrea los servicios con la imagen nueva y conserva los volúmenes nombrados. Para revisar el estado tras la actualización:

```sh
docker compose logs --tail=100 backend web caddy
curl -fsS https://tv.midominio.com/health
```

Para volver al código anterior, selecciona el commit anterior con Git y vuelve a ejecutar `docker compose up -d --build`. No borres el volumen de datos al hacer rollback.

## 6. Copia de seguridad de SQLite

Haz la copia con la API activa usando la función de backup de SQLite, que incluye de forma segura los datos aunque la base use WAL. El siguiente comando genera un archivo en el directorio actual del servidor:

```sh
BACKUP="on-air-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
docker compose exec -T backend python -c 'import sqlite3; s=sqlite3.connect("/data/on-air.sqlite3"); d=sqlite3.connect("/tmp/on-air-backup.sqlite3"); s.backup(d); d.close(); s.close()'
docker cp "$(docker compose ps -q backend):/tmp/on-air-backup.sqlite3" "$BACKUP"
```

Copia ese archivo fuera del servidor o a almacenamiento de backups protegido y define una retención. También conserva los volúmenes `caddy-data` y `caddy-config`: contienen el estado TLS y la configuración de Caddy.

Para restaurar SQLite, detén el backend, copia el archivo de backup a `/data/on-air.sqlite3` dentro del contenedor o volumen y vuelve a levantarlo. La restauración reemplaza el catálogo y las guías guardadas, así que verifica primero que elegiste el backup correcto.

> `docker compose down` mantiene los volúmenes. Evita `docker compose down -v`: esa opción elimina también el catálogo, las guías y el estado de certificados guardados.

## 7. Operación y diagnóstico

- **Estado de servicios:** `docker compose ps`.
- **Logs en vivo:** `docker compose logs -f caddy web backend`.
- **Forzar reconstrucción:** `docker compose build --no-cache web backend && docker compose up -d`.
- **Certificado no emitido:** confirma DNS público, disponibilidad externa de TCP 80/443 y que no haya otro proceso ocupando los puertos; consulta los logs de Caddy.
- **Catálogo vacío o antiguo:** revisa `docker compose logs backend` y `https://tv.midominio.com/api/v1/status`. El backend conserva la última copia válida cuando el proveedor falla.
- **Guía no disponible:** verifica que el país exista en IPTV-EPG y revisa los logs del backend. Un fallo no reemplaza una guía válida almacenada para ese día.
- **Espacio y backups:** monitorea el disco donde Docker guarda los volúmenes y prueba periódicamente la restauración de una copia.

El volumen `onair-data` guarda el archivo SQLite; Caddy maneja certificados y redirección HTTP a HTTPS automáticamente al tener un dominio público en el Caddyfile. [Configuración de reverse proxy de Caddy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
