# On Air

Aplicación de escritorio para explorar y reproducir canales públicos de IPTV-org. El proyecto cubre el esqueleto de escritorio y la primera versión del catálogo y reproductor (fases 0 y 1 de `Espec.md`).

## Requisitos

- Node.js 20.19+ o 22.12+
- Rust estable y las dependencias de Tauri 2 para tu plataforma: https://v2.tauri.app/start/prerequisites/

## Desarrollo

```sh
npm install
npm run tauri dev
```

Para trabajar solo en la interfaz web, usa `npm run dev`. Para compilar frontend y escritorio usa `npm run build` y `npm run tauri build`.

## Atajos del reproductor

- `Espacio`: reproducir o pausar.
- `F`: pantalla completa.
- `M`: silenciar o activar sonido.
- `↑` / `↓`: subir o bajar volumen.
- `PageUp` / `PageDown`: canal anterior o siguiente.
- `/`: enfocar la búsqueda cuando el reproductor está cerrado.
- `Esc`: cerrar el reproductor.

La interfaz usa SvelteKit en modo SPA con `adapter-static` y Tauri 2. Ambas versiones consumen el backend compartido, que descarga y cruza los ocho JSON de `https://iptv-org.github.io/api/` y filtra canales cerrados, bloqueados, NSFW y sin streams. SQLite guarda el catálogo en el servidor y IndexedDB conserva una copia de respaldo en cada cliente para abrir el último catálogo si el backend no responde. Al no estar implementado todavía el proxy de streams, los streams que requieren cabeceras personalizadas o no habilitan CORS pueden no reproducirse; se prueban automáticamente las alternativas publicadas para ese canal. Si no hay catálogo ni copia local, «Probar el reproductor» abre una señal HLS de demostración pública.

## Estado

- **Fase 0:** shell Tauri/Svelte, interfaz ejecutable y reproductor HLS de muestra. La matriz de reproducción por plataforma aún no está verificada.
- **Fase 1 (parcial):** el backend importa y cruza el catálogo compartido cada 12 horas; la interfaz mantiene búsqueda, filtros, vistas virtualizadas y fallback entre streams. Pendiente validar reproducción real y añadir el proxy seguro.
- **Fase 2 (parcial):** SQLite conserva el catálogo central y IndexedDB sirve como copia local sin conexión. Pendiente el proxy de streams y la comprobación de salud.
- **Fase 3 (parcial):** favoritos, vistos recientes, filtros y tema Sistema/Claro/Oscuro persistidos localmente, con restauración al reabrir; selector de calidad HLS, Picture-in-Picture si el webview lo admite y controles de volumen por teclado. Pendientes interfaz en inglés y ventana siempre visible.

## Backend compartido (web y escritorio)

El backend de `backend/server.py` publica una API compartida para las apps y guarda su estado en SQLite. El catálogo público se importa de IPTV-org al iniciar y se vuelve a sincronizar cada 12 horas (configurable). La guía XMLTV de IPTV-EPG se importa por país cuando un cliente la solicita por primera vez en el día UTC; solicitudes posteriores ese mismo día reciben la copia compartida del servidor. Si falla una actualización del catálogo, el backend sigue sirviendo la última copia disponible. Los horarios de la guía se convierten a epoch UTC.

### Desarrollo local

Requiere Python 3.10+ y Node.js ya indicados arriba. En una terminal inicia la API:

```sh
python3 backend/server.py
```

En otra, ejecuta la app con `npm run dev` o `npm run tauri dev`. Vite reenvía `/api` y `/health` a `http://127.0.0.1:8000`. La primera sincronización del catálogo ocurre en segundo plano, así que puede tardar antes de aparecer el listado.

### Despliegue web

El despliegue incluye API y web estática en Docker Compose, detrás del Caddy que ya está instalado en el host. La web solo se publica en `127.0.0.1:8080`; la guía para configurar el sitio en Caddy, DNS, firewall, `.env`, backups, actualizaciones y diagnóstico está en [DEPLOY_CADDY.md](DEPLOY_CADDY.md). Resumen:

```sh
cp .env.example .env
# Edita DOMAIN y CORS_ORIGINS en .env
docker compose up --build -d
```

El Caddy del host acepta el tráfico externo y reenvía al puerto loopback de la web; la API no se expone directamente. Caddy obtiene y renueva TLS para el dominio. La API solo expone lectura pública; no hay operaciones de edición ni cuentas de usuario. `GET /api/v1/status` muestra la última sincronización. Endpoints principales: `GET /api/v1/channels`, `GET /api/v1/guides?country=PE` y `GET /health`.

Para compilar una app de escritorio de release, apuntar el bundle al dominio público de la API:

```sh
VITE_API_BASE_URL=https://api.tu-dominio.example npm run tauri build
```

En web, la variable puede quedar vacía porque Nginx sirve la web y reenvía `/api` al backend por el mismo origen. Favoritos, vistos recientes, filtros y tema permanecen en almacenamiento local del cliente.

La caché diaria de guías usa el día UTC como clave compartida del servidor. Si el producto requiere reiniciar esa ventana según una zona horaria específica, habrá que definirla antes del despliegue final.
