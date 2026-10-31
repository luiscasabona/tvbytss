Voy a revisar el repositorio de la API para basar las especificaciones en los endpoints y campos actuales.

# Especificaciones: On Air (Svelte + Tauri + API compartida)

Revisé el README de la API para que las especificaciones se ajusten a los endpoints y campos actuales.

## 1. Alcance

**Objetivo:** app de escritorio multiplataforma y app web para explorar canales, favoritos locales y programación. Ambas consumen un backend compartido que importa y publica los datos de catálogo y guía.

**Fuera del MVP:** grabación, EPG completa, Chromecast, cuentas de usuario.

## 2. Stack propuesto

| Capa | Tecnología |
|---|---|
| UI | Svelte 5 + SvelteKit (modo SPA, `adapter-static`) + TypeScript |
| Estilos | Tailwind CSS (opcional: shadcn-svelte o Skeleton) |
| Shell de escritorio | Tauri 2 |
| API compartida | Python 3 + HTTP API; SQLite persistente para catálogo, guías e historial de sincronización |
| Importación | IPTV-org cada 12 h; IPTV-EPG bajo demanda una vez por país y día UTC |
| Web | SvelteKit SPA estática detrás de Nginx, con `/api` reenviado al backend |
| Reproductor | `hls.js` sobre `<video>` (MVP); `libmpv` como fase 2 |
| Persistencia | `tauri-plugin-store` (ajustes y favoritos) y SQLite o archivos JSON (caché) |
| Virtualización | `@tanstack/svelte-virtual` (la lista tiene miles de canales) |

## 3. Datos de la API

Todos los endpoints son JSON estáticos en `https://iptv-org.github.io/api/`.

| Endpoint | Uso en la app |
|---|---|
| `channels.json` | Catálogo base: nombre, país, categorías, `is_nsfw`, `closed`, `website` |
| `streams.json` | URL del stream (`url`), `quality`, `labels`, `referrer`, `user_agent` |
| `logos.json` | Logos por canal (`url`, `in_use`, `tags`) |
| `categories.json` | Filtro de categorías |
| `countries.json` | Filtro de países (con bandera emoji) |
| `languages.json` | Filtro de idiomas |
| `feeds.json` | Idiomas y área de emisión de cada feed |
| `blocklist.json` | Excluir canales bloqueados (DMCA o NSFW) |
| `guides.json` | Fase 2: información de EPG |

**Modelo unificado en la app**, resultado de cruzar los datos al cargar:

```ts
interface Channel {
  id: string;                // channels.id
  name: string;
  altNames: string[];
  country: string;           // código ISO
  categories: string[];
  languages: string[];       // vía feeds
  logo?: string;             // logo con in_use=true, preferir SVG/PNG
  streams: Stream[];         // 1..n por canal
  isFavorite: boolean;
}
interface Stream {
  url: string;
  quality?: string;
  labels: ("Geo-blocked" | "Not 24/7")[];
  referrer?: string;
  userAgent?: string;
}
```

**Reglas de limpieza al construir el catálogo:**
- Descartar canales con `closed != null` (cerrados).
- Descartar los que estén en `blocklist.json`.
- Descartar `is_nsfw = true` por defecto, con opción en ajustes (protegida con confirmación).
- Descartar los `streams` con `channel = null`.
- Ordenar los streams de cada canal por calidad.

## 4. Requisitos funcionales

### 4.1 Listado de canales
- Vista en cuadrícula (logo y nombre) y en lista.
- Lista virtualizada con scroll fluido para más de 10 000 elementos.
- Búsqueda por nombre y `alt_names`, con debounce y tolerancia a acentos.
- Indicadores visibles: calidad, "Geo-blocked", "Not 24/7".

### 4.2 Filtros (combinables)
- País (multiselección, con búsqueda dentro del selector).
- Categoría (news, sports, kids, documentary, etc.).
- Idioma.
- Calidad mínima (SD, 720p, 1080p).
- Solo favoritos.
- Ocultar canales con etiqueta "Geo-blocked" o "Not 24/7".
- Filtros guardados en la URL interna o en el store, para que se restauren al reabrir la app.

### 4.3 Reproductor
- Reproducción HLS (`.m3u8`) con controles: play/pausa, volumen, silencio, pantalla completa y selector de calidad si el manifiesto lo ofrece.
- Cambio rápido de canal (anterior/siguiente dentro de la lista filtrada, y por número).
- Si un stream falla, intentar automáticamente el siguiente `stream` del canal y avisar con un mensaje claro ("Canal no disponible").
- Reconexión automática ante cortes breves.
- Modo Picture-in-Picture y ventana siempre visible (opcional).
- Atajos de teclado: `Espacio`, `F`, `M`, `↑/↓` (volumen), `PgUp/PgDn` (cambiar canal), `/` (buscar).

### 4.4 Personalización
- Favoritos y "vistos recientemente".
- Tema claro, oscuro o del sistema.
- Idioma de la interfaz (ES/EN con `svelte-i18n` o Paraglide).

### 4.5 Actualización de datos
- Primera carga: descarga de los JSON y construcción del catálogo.
- Caché local con TTL (por ejemplo, 12 h) y botón "Actualizar ahora".
- Modo sin conexión: mostrar el catálogo cacheado, indicando que no se puede reproducir.
- Revalidación con `ETag` o `If-Modified-Since` para ahorrar ancho de banda.

## 5. Desafíos técnicos (conviene decidirlos desde el inicio)

1. **CORS y cabeceras personalizadas.** Muchos streams requieren `Referer` o `User-Agent` específicos (campos `referrer` y `user_agent`), y el navegador no permite fijarlos. **Solución:** un proxy local en Rust (por ejemplo con `axum` o `hyper`, en `127.0.0.1:<puerto aleatorio>`) que reciba la petición del `<video>`, añada las cabeceras y reescriba las URLs relativas de los manifiestos. Esto también resuelve CORS.

2. **Contenido mixto (HTTP desde un origen HTTPS).** Muchos streams son `http://`. Con el proxy local el problema desaparece, porque el reproductor solo habla con `127.0.0.1`.

3. **Compatibilidad del webview.** Tauri usa el webview del sistema (WebView2, WKWebView, WebKitGTK), y el soporte de HLS y códecs varía. `hls.js` cubre la mayoría de los casos con MSE. En Linux hay que verificar que estén instalados los plugins de GStreamer. Si la compatibilidad es insuficiente, la alternativa robusta es **embeber mpv** (`libmpv`) desde Rust, que reproduce casi cualquier formato (HLS, DASH, RTMP, TS).

4. **Streams caídos.** Es habitual que una parte importante no funcione. Hay que contemplarlo en la UX: **comprobación de salud** bajo demanda (petición HEAD o primer segmento) y marcar los fallos de forma temporal en la caché local.

5. **Rendimiento.** Hacer el cruce de `channels`, `streams`, `logos` y `feeds` en Rust (comando Tauri) y enviar al frontend solo el resultado ya unificado, en lugar de procesar varios JSON grandes en JS.

## 6. Arquitectura

```
┌──────────────────┐    HTTPS    ┌──────────────────────────┐
│ Tauri escritorio ├─────────────►│                          │
└──────────────────┘             │ API Python + SQLite      ├── IPTV-org (auto, 12 h)
                                 │ catálogo y guías públicas├── IPTV-EPG (bajo demanda)
┌──────────────────┐    HTTPS    │                          │
│ Web Svelte       ├─────────────►│ caché diaria por país    │
└──────────────────┘             └──────────────────────────┘
```

**Estructura de carpetas sugerida**
```
src/
  lib/
    components/   (ChannelCard, FilterPanel, Player, SearchBar)
    stores/       (filters.ts, player.ts, favorites.ts, settings.ts)
    types.ts
    i18n/
  routes/+page.svelte
backend/
  server.py       (API, importación y almacenamiento persistente)
deploy/
  nginx.conf      (web estática y proxy de API)
```

## 7. Requisitos no funcionales

- **Arranque** en menos de 3 s con caché; carga inicial sin caché en menos de 10 s con conexión normal.
- **Memoria** razonable (menos de 400 MB con reproducción activa).
- **Seguridad:** CSP estricta, capabilities de Tauri mínimas (solo `http`, `store`, `fs` para caché y `shell` si usas mpv). El proxy solo debe aceptar peticiones del propio webview (token por sesión) y escuchar únicamente en loopback.
- **Privacidad:** sin telemetría; todos los datos del usuario quedan en local.
- **Accesibilidad:** navegación completa por teclado, contraste adecuado, etiquetas ARIA.
- **Empaquetado:** instaladores `.msi`/`.exe`, `.dmg` y `.AppImage`/`.deb`; actualizaciones con `tauri-plugin-updater`.

## 8. Plan incremental: una app utilizable al cierre de cada fase

Cada fase entrega una versión ejecutable de escritorio, con un recorrido completo que se puede probar de principio a fin. El alcance de una fase se considera terminado cuando pasa sus criterios de salida; las fases posteriores amplían la app sin volverla inutilizable.

### Estado de implementación — 2026-10-31

| Fase | Estado | Evidencia y pendiente principal |
|---|---|---|
| 0 — Esqueleto y reproducción de prueba | **Implementación presente; salida pendiente** | Shell SvelteKit/Tauri, estados básicos y señal HLS de muestra están en el código. Falta ejecutar la app y registrar compatibilidad por webview/plataforma para cumplir los criterios de salida. |
| 1 — Catálogo y primera experiencia de TV | **En progreso** | Backend compartido importa y cruza los ocho JSON de forma automática cada 12 h; clientes escritorio/web consultan la API. Falta verificar la ejecución integrada y reproducción real. |
| 2 — Persistencia, proxy y offline | **En progreso** | SQLite del servidor guarda el catálogo; IndexedDB conserva un respaldo del cliente para falta de conexión. El proxy de streams sigue pendiente. |
| 3 — Personalización | **En progreso** | Favoritos, vistos recientes, filtros y tema claro/oscuro/sistema se guardan/restauran; el reproductor ofrece volumen por teclado, calidad HLS y PiP cuando el webview lo soporta. Falta idioma ES/EN y ventana siempre visible. |
| 4 — EPG y distribución | **En progreso** | La API importa XMLTV de IPTV-EPG al primer pedido diario por país y comparte la copia entre clientes. Falta validar calidad/correspondencia de la guía y configurar dominio, TLS y paquetes de distribución. |

No se marca todavía ninguna fase como cerrada: los criterios de salida incluyen pruebas de ejecución y compatibilidad que aún no están registradas. La compilación de frontend y `cargo check` en macOS sí se han verificado.

### Fase 0 — Esqueleto ejecutable y prueba de reproducción *(implementación presente; validación pendiente)*

**Objetivo:** validar pronto el shell de escritorio, el empaquetado de desarrollo y la reproducción en los webviews objetivo.

- Crear el proyecto SvelteKit en modo SPA, TypeScript y Tauri 2.
- Crear una pantalla inicial con estados de carga, error y reproducción; incluir controles mínimos de play/pausa y volumen.
- Reproducir un stream HLS de prueba configurable, usando `hls.js` cuando se requiera MSE y reproducción nativa cuando esté disponible.
- Documentar cómo ejecutar la app en Windows, macOS y Linux, y registrar las limitaciones de codecs/webview encontradas.

**App al cierre:** aplicación de escritorio que abre, presenta la interfaz y reproduce el stream de prueba en los sistemas de desarrollo disponibles.

**Criterios de salida:** arranque y cierre fiables; errores de red o de formato se muestran en la interfaz; se ha comprobado la ruta de reproducción en cada plataforma objetivo disponible. Esta fase no depende de la API ni promete que todos los canales reales reproduzcan.

### Fase 1 — Catálogo real y primera experiencia de TV *(en progreso)*

**Objetivo:** poder encontrar un canal del catálogo público y reproducirlo.

- Descargar `channels`, `streams`, `logos`, `feeds`, `blocklist`, `categories`, `countries` y `languages`; unificar los datos en Rust.
- Aplicar las reglas de limpieza del modelo: cerrados, bloqueados, NSFW ocultos por defecto, streams sin canal y orden por calidad.
- Mostrar canales en cuadrícula y lista con búsqueda tolerante a acentos, filtros multiselección de país con búsqueda interna y categoría, y lista virtualizada. *(Implementado en frontend.)*
- Abrir el reproductor al seleccionar un canal; ofrecer anterior/siguiente en el conjunto visible y fallback al siguiente stream si falla el primero.
- Incorporar estados vacíos, error de catálogo y canal no disponible.

**App al cierre:** catálogo navegable y búsqueda funcional; un canal puede abrirse y reproducirse cuando su stream es compatible y está disponible.

**Criterios de salida:** la app no se bloquea durante la descarga o el filtrado; el catálogo vacío/degradado tiene explicación y acción de reintento; el usuario puede volver a la lista después de un fallo.

### Fase 2 — Persistencia, proxy y uso sin conexión *(en progreso)*

**Objetivo:** hacer reproducibles más streams y conservar la utilidad de la app ante fallos de red.

- Añadir caché de catálogo persistente en el webview con TTL de 12 h y revalidación condicional; añadir acción «Actualizar ahora». *(Implementado con IndexedDB; depende de que la API exponga validadores por CORS.)*
- Añadir proxy HTTP local en loopback para streams, cabeceras `Referer`/`User-Agent`, CORS, HTTP y reescritura de manifiestos/segmentos.
- Proteger el proxy con token de sesión, validar destinos y limitarlo al loopback.
- Servir el catálogo cacheado sin conexión e indicar claramente que no se puede iniciar reproducción offline.
- Añadir comprobación de salud bajo demanda y caché temporal de fallos.

**App al cierre:** app utilizable con catálogo previamente descargado sin conexión y reproducción de streams que necesitan cabeceras o proxy.

**Criterios de salida:** el proxy se inicia y detiene junto con la app, no escucha en interfaces públicas y la cancelación de reproducción libera recursos; el catálogo cacheado sobrevive a reinicios.

### Fase 3 — Personalización y navegación diaria

**Objetivo:** recordar preferencias y facilitar sesiones de uso habituales.

- Añadir favoritos y vistos recientemente persistidos localmente. *(Implementado con almacenamiento local del webview y secciones de navegación.)*
- Completar filtros combinables: idioma, calidad mínima y exclusión de etiquetas; restaurar filtros al reabrir. *(Implementado; los filtros se persisten localmente.)*
- Añadir tema claro/oscuro/sistema, interfaz ES/EN y atajos de teclado documentados. *(Tema y atajos implementados; traducción completa de interfaz ES/EN pendiente.)*
- Añadir selector de calidad cuando el manifiesto HLS ofrezca niveles, PiP y opción de ventana siempre visible si la plataforma lo admite. *(Selector HLS y PiP implementados con degradación por capacidad; ventana siempre visible pendiente.)*
- Permitir habilitar contenido NSFW desde ajustes con confirmación explícita.

**App al cierre:** preferencias y listas personales se conservan; la navegación y reproducción pueden operarse con ratón y teclado.

**Criterios de salida:** preferencias persistidas sobreviven reinicios; controles con etiquetas accesibles; las funciones no soportadas por un sistema se ocultan o explican sin romper el flujo principal.

### Fase 4 — EPG y distribución

**Objetivo:** añadir guía y entregar paquetes instalables actualizables.

- Integrar `guides.json` y una vista de programación con alcance acotado; asociar guías por canal cuando exista correspondencia fiable.
- Evaluar `libmpv` como alternativa seleccionable si las pruebas de compatibilidad de HLS/códecs justifican el cambio; no sustituir `hls.js` sin una comparación funcional por plataforma.
- Preparar instaladores `.msi`/`.exe`, `.dmg` y `.AppImage`/`.deb`; configurar firma y actualizaciones con Tauri updater según disponibilidad de certificados.
- Considerar exportación M3U como extra, manteniendo avisos sobre restricciones y metadatos que no se pueden representar.

**App al cierre:** versión instalable con guía de programación disponible cuando hay datos y con un canal de actualización definido.

**Criterios de salida:** instalación, apertura, actualización y desinstalación documentadas y verificadas en los sistemas publicados; la ausencia de datos EPG no afecta al catálogo ni al reproductor.

## 9. Trabajo transversal en todas las fases

Estos temas atraviesan todas las entregas; no se posponen como una fase final:

| Eje | Aplicación desde la primera fase |
|---|---|
| **Accesibilidad y UX** | Estados de carga/error/vacío, navegación por teclado, foco visible, nombres accesibles y mensajes accionables. Revisar cada pantalla nueva. |
| **Seguridad y privacidad** | CSP y permisos mínimos de Tauri desde el esqueleto; sin telemetría; datos personales en local; validar URLs y limitar el proxy cuando se introduzca. |
| **Compatibilidad** | Mantener una matriz por sistema operativo/webview para reproducción, atajos, PiP y empaquetado; decidir degradación por capacidad. |
| **Rendimiento** | Medir arranque y uso de memoria al añadir catálogo y reproducción; virtualizar desde la primera lista grande; procesar y cruzar JSON en Rust. |
| **Resiliencia** | Diseñar estados y recuperación para red caída, API inválida, streams caídos, caché antigua y cancelación; nunca dejar una pantalla bloqueada sin salida. |
| **Calidad de datos** | Tolerar campos opcionales y registros incompletos; no asumir que todos los canales tienen logo, idioma, guía o stream reproducible. |
| **Distribución** | Mantener una compilación ejecutable en cada fase; documentar comandos y decisiones; verificar paquetes cuando se incorpore empaquetado. |

## 10. Decisiones de diseño que conviene cerrar antes de implementar

1. **Nombre y formato del primer release:** prototipo de desarrollo instalable o artefactos firmados para usuarios finales. La Fase 0 puede producir app ejecutable sin resolver todavía firma y actualización.
2. **Matriz inicial de plataformas:** confirmar sistemas y versiones mínimas que se van a soportar; probar el webview real, especialmente HLS, codecs y GStreamer en Linux.
3. **Límite de alcance de la guía:** `guides.json` puede no ser una EPG completa o uniforme; definir correspondencia por canal y manejo de horarios antes de prometer programación fiable.
4. **Política de reproducción:** definir timeout y número máximo de reintentos/fallback para evitar esperas largas al cambiar de canal.
5. **Persistencia:** comenzar con store para ajustes/favoritos y caché de catálogo como JSON versionado; introducir SQLite solo si los índices o escrituras medidas lo requieren.
6. **Proxy:** confirmar implementación Rust y estrategia de reescritura HLS antes de Fase 2; bloquear esquemas/destinos inseguros y no aceptar solicitudes de sitios arbitrarios.

## 11. Fuera de alcance inicial

Grabación, cuentas de usuario, sincronización en nube, Chromecast y una EPG completa siguen fuera del MVP. PiP, `libmpv`, actualizaciones y M3U se implementan solo después de que el catálogo y la reproducción básica sean estables.

