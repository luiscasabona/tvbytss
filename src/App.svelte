<script lang="ts">
  import Hls from 'hls.js';
  import { onMount, tick } from 'svelte';
  import { Search, Radio, Play, Pause, ChevronLeft, ChevronRight, Volume2, VolumeX, Maximize, Maximize2, Minimize2, RotateCw, Tv, X, Signal, ArrowUpRight, Grid2X2, List, ChevronDown, Star, Clock3, PictureInPicture2, CalendarDays } from 'lucide-svelte';
  import { loadChannels, loadCountryGuide, type Channel, type CountryGuide, type GuideProgram } from './lib/types';

  let channels: Channel[] = $state([]);
  let loading = $state(true);
  let error = $state('');
  let catalogCached = $state(false);
  let catalogUpdatedAt = $state(0);
  let query = $state('');
  let searchText = $state('');
  let selectedCountries = $state<string[]>([]);
  let countrySearch = $state('');
  let category = $state('all');
  let language = $state('all');
  let minQuality = $state('all');
  let hideGeoBlocked = $state(false);
  let hideNon24 = $state(false);
  let filtersReady = $state(false);
  let themeMode = $state<'system' | 'light' | 'dark'>('system');
  let library = $state<'all' | 'favorites' | 'recent'>('all');
  let favorites = $state<string[]>([]);
  let recentlyViewed = $state<string[]>([]);
  let listView = $state(false);
  let selected: Channel | null = $state(null);
  let playError = $state('');
  let playing = $state(false);
  let muted = $state(false);
  let volume = $state(0.8);
  let currentStream = $state(0);
  let availableQualities = $state<Array<{ index: number; label: string }>>([]);
  let qualityLevel = $state(-1);
  let pipSupported = $state(false);
  let pipActive = $state(false);
  let playerExpanded = $state(false);
  let guideMode = $state(false);
  let guideCountry = $state('PE');
  let guideLoading = $state(false);
  let guideError = $state('');
  let guide: CountryGuide | null = $state(null);
  let video: HTMLVideoElement;
  let hls: Hls | null = null;
  let abortController: AbortController | undefined;
  let gridElement: HTMLDivElement;
  let scrollY = $state(0);
  let gridTop = $state(0);
  let columns = $state(4);
  const rowHeight = $derived(listView ? 96 : 187);
  const overscanRows = 2;
  const demoStream = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8';

  const countryNames = new Intl.DisplayNames(['es'], { type: 'region' });
  const countries = $derived([...new Set(channels.map((channel) => channel.country))].sort());
  const guideCountries = ['AL','AR','AM','AU','AT','BY','BE','BO','BA','BR','BG','CA','CL','CO','CR','HR','CW','CZ','DK','DO','SV','FI','FR','GE','DE','GH','GR','GT','HN','HK','HU','IS','IN','ID','IL','IT','JM','JP','LV','LT','LU','MY','MT','MX','ME','NL','NZ','NI','NG','NO','PA','PY','PE','PL','PT','RO','RU','RS','SG','ZA','ES','SE','CH','TW','TH','TR','UG','GB','US','UY','VE','ZW'];
  const guideCountryName = (code: string) => countryNames.of(code) ?? code;
  const guideChannelRows = $derived(guide ? [...new Set(guide.programs.map((program) => program.channelId))]
    .map((id) => ({ channel: channels.find((item) => item.id === id), programs: guide!.programs.filter((program) => program.channelId === id) }))
    .filter((row): row is { channel: Channel; programs: GuideProgram[] } => Boolean(row.channel))
    .sort((a, b) => a.channel.name.localeCompare(b.channel.name)) : []);
  const languages = $derived([...new Set(channels.flatMap((channel) => channel.languages))].sort());
  const visibleCountries = $derived(countries.filter((code) => normalize(`${countryNames.of(code) ?? code} ${code}`).includes(normalize(countrySearch))));
  const categories = $derived([...new Set(channels.flatMap((channel) => channel.categories))].sort());
  const libraryChannels = $derived(library === 'favorites'
    ? channels.filter((channel) => favorites.includes(channel.id))
    : library === 'recent'
      ? recentlyViewed.map((id) => channels.find((channel) => channel.id === id)).filter((channel): channel is Channel => Boolean(channel))
      : channels);
  const filtered = $derived(libraryChannels.filter((channel) => {
    const search = normalize(query);
    const match = !search || normalize([channel.name, ...channel.altNames].join(' ')).includes(search);
    const labels = channel.streams.flatMap((stream) => stream.labels ?? []);
    const bestQuality = Math.max(0, ...channel.streams.map((stream) => qualityRank(stream.quality)));
    return match
      && (!selectedCountries.length || selectedCountries.includes(channel.country))
      && (category === 'all' || channel.categories.includes(category))
      && (language === 'all' || channel.languages.includes(language))
      && (minQuality === 'all' || bestQuality >= qualityRank(minQuality))
      && (!hideGeoBlocked || !labels.includes('Geo-blocked'))
      && (!hideNon24 || !labels.includes('Not 24/7'));
  }));
  $effect(() => {
    if (!filtersReady) return;
    saveFilterPreferences({ query: searchText, countries: selectedCountries, category, language, minQuality, hideGeoBlocked, hideNon24 });
  });
  $effect(() => {
    const timeout = window.setTimeout(() => { query = searchText; }, 180);
    return () => window.clearTimeout(timeout);
  });
  const firstRow = $derived(Math.max(0, Math.floor(Math.max(0, scrollY - gridTop) / rowHeight) - overscanRows));
  const visibleRows = $derived(Math.ceil((window.innerHeight || 800) / rowHeight) + overscanRows * 2);
  const visibleChannels = $derived(filtered.slice(firstRow * columns, (firstRow + visibleRows) * columns));
  const beforeSpace = $derived(firstRow * rowHeight);
  const afterSpace = $derived(Math.max(0, Math.ceil(filtered.length / columns) * rowHeight - beforeSpace - visibleRows * rowHeight));

  function normalize(value: string) {
    return value.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function qualityRank(quality?: string) {
    if (!quality) return 0;
    if (/4k|2160p/i.test(quality)) return 2160;
    if (/1080p|fhd/i.test(quality)) return 1080;
    if (/720p|hd/i.test(quality)) return 720;
    if (/576p/i.test(quality)) return 576;
    if (/480p|sd/i.test(quality)) return 480;
    const match = quality.match(/(\d{3,4})p/i);
    return match ? Number(match[1]) : 0;
  }

  function savePreference(key: string, value: string[]) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* La reproducción y navegación no dependen del almacenamiento local. */ }
  }

  function saveFilterPreferences(value: Record<string, unknown>) {
    try { localStorage.setItem('on-air-filters-v1', JSON.stringify(value)); } catch { /* Los filtros siguen funcionando durante esta sesión. */ }
  }

  function applyTheme(mode: 'system' | 'light' | 'dark') {
    themeMode = mode;
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;
    try { localStorage.setItem('on-air-theme-v1', mode); } catch { /* El tema elegido dura al menos durante la sesión. */ }
  }

  function toggleCountry(code: string, checked: boolean) {
    selectedCountries = checked ? [...selectedCountries, code] : selectedCountries.filter((item) => item !== code);
  }

  function toggleFavorite(id: string) {
    favorites = favorites.includes(id) ? favorites.filter((item) => item !== id) : [id, ...favorites];
    savePreference('on-air-favorites-v1', favorites);
  }

  async function refresh() {
    abortController?.abort();
    abortController = new AbortController();
    loading = true;
    error = '';
    try {
      const result = await loadChannels(abortController.signal);
      channels = result.channels;
      catalogCached = result.cached;
      catalogUpdatedAt = result.updatedAt;
      await tick();
      measureGrid();
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') return;
      error = 'No se pudo descargar el catálogo. Revisa tu conexión e inténtalo de nuevo.';
    } finally {
      loading = false;
    }
  }

  async function loadGuide() {
    guideLoading = true;
    guideError = '';
    try { guide = await loadCountryGuide(guideCountry); }
    catch (cause) {
      guide = null;
      const detail = typeof cause === 'string' ? cause : cause instanceof Error ? cause.message : '';
      guideError = detail
        ? `No se pudo cargar la programación: ${detail}`
        : 'No se pudo cargar la programación. Comprueba tu conexión e inténtalo de nuevo.';
    }
    finally { guideLoading = false; }
  }

  function showGuide() { guideMode = true; library = 'all'; }
  function formatGuideTime(timestamp: number) { return new Date(timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' }); }

  async function openChannel(channel: Channel) {
    selected = channel;
    if (channel.id !== 'demo-hls') {
      recentlyViewed = [channel.id, ...recentlyViewed.filter((id) => id !== channel.id)].slice(0, 100);
      savePreference('on-air-recent-v1', recentlyViewed);
    }
    currentStream = 0;
    playError = '';
    await tick();
    pipSupported = Boolean(document.pictureInPictureEnabled && video?.requestPictureInPicture);
    playStream();
  }

  function playDemo() {
    openChannel({ id: 'demo-hls', name: 'Prueba HLS', altNames: [], country: 'US', categories: [], streams: [{ channel: 'demo-hls', url: demoStream, quality: 'DEMO' }] });
  }

  function playStream() {
    if (!selected || !video) return;
    const stream = selected.streams[currentStream];
    if (!stream) { playError = 'Canal no disponible'; playing = false; return; }
    hls?.destroy(); hls = null;
    availableQualities = [];
    qualityLevel = -1;
    video.pause(); video.removeAttribute('src'); video.load();
    video.volume = volume;
    video.muted = muted;
    const isHls = stream.url.toLowerCase().includes('.m3u8');
    if (isHls && Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, startLevel: -1 });
      hls.loadSource(stream.url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        availableQualities = hls?.levels.map((level, index) => ({ index, label: level.name || (level.height ? `${level.height}p` : `${(level.bitrate / 1_000_000).toFixed(1)} Mbps`) })) ?? [];
        video.play().catch(() => {});
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        hls?.destroy(); hls = null;
        if (currentStream + 1 < selected!.streams.length) { currentStream += 1; playStream(); }
        else { playError = 'Canal no disponible. Prueba otro canal.'; playing = false; }
      });
    } else {
      video.src = stream.url;
      video.play().catch(() => {
        if (currentStream + 1 < selected!.streams.length) { currentStream += 1; playStream(); }
        else { playError = 'Este stream no se pudo reproducir en tu dispositivo.'; }
      });
    }
  }

  function closePlayer() { hls?.destroy(); hls = null; video?.pause(); if (document.pictureInPictureElement) void document.exitPictureInPicture().catch(() => {}); pipActive = false; playerExpanded = false; selected = null; playing = false; }
  function stepChannel(step: number) {
    if (!selected || !filtered.length) return;
    const index = filtered.findIndex((item) => item.id === selected?.id);
    openChannel(filtered[(index + step + filtered.length) % filtered.length]);
  }
  function togglePlay() { if (!video) return; if (video.paused) video.play().catch(() => {}); else video.pause(); }
  function fullScreen() { video?.requestFullscreen?.(); }
  async function togglePictureInPicture() {
    if (!video) return;
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else await video.requestPictureInPicture();
      pipActive = Boolean(document.pictureInPictureElement);
    } catch { pipSupported = false; }
  }
  function selectQuality(event: Event) {
    qualityLevel = Number((event.currentTarget as HTMLSelectElement).value);
    if (hls) hls.currentLevel = qualityLevel;
  }
  function setVolume(event: Event) { volume = Number((event.target as HTMLInputElement).value); if (video) video.volume = volume; }
  function measureGrid() {
    if (!gridElement) return;
    gridTop = gridElement.getBoundingClientRect().top + window.scrollY;
    columns = listView ? 1 : Math.max(1, Math.floor((gridElement.clientWidth + 12) / 200));
  }

  function updateScroll() { scrollY = window.scrollY; }

  onMount(() => {
    try {
      const storedFavorites = JSON.parse(localStorage.getItem('on-air-favorites-v1') ?? '[]');
      const storedRecent = JSON.parse(localStorage.getItem('on-air-recent-v1') ?? '[]');
      if (Array.isArray(storedFavorites)) favorites = storedFavorites.filter((id): id is string => typeof id === 'string');
      if (Array.isArray(storedRecent)) recentlyViewed = storedRecent.filter((id): id is string => typeof id === 'string').slice(0, 100);
      const storedTheme = localStorage.getItem('on-air-theme-v1');
      if (storedTheme === 'light' || storedTheme === 'dark' || storedTheme === 'system') themeMode = storedTheme;
      const storedFilters = JSON.parse(localStorage.getItem('on-air-filters-v1') ?? 'null');
      if (storedFilters && typeof storedFilters === 'object') {
        if (typeof storedFilters.query === 'string') { searchText = storedFilters.query; query = storedFilters.query; }
        if (Array.isArray(storedFilters.countries)) selectedCountries = storedFilters.countries.filter((id: unknown): id is string => typeof id === 'string');
        if (typeof storedFilters.category === 'string') category = storedFilters.category;
        if (typeof storedFilters.language === 'string') language = storedFilters.language;
        if (typeof storedFilters.minQuality === 'string') minQuality = storedFilters.minQuality;
        if (typeof storedFilters.hideGeoBlocked === 'boolean') hideGeoBlocked = storedFilters.hideGeoBlocked;
        if (typeof storedFilters.hideNon24 === 'boolean') hideNon24 = storedFilters.hideNon24;
      }
    } catch { /* Una preferencia local dañada no debe impedir abrir el catálogo. */ }
    applyTheme(themeMode);
    filtersReady = true;
    void refresh();
    window.addEventListener('scroll', updateScroll, { passive: true });
    window.addEventListener('resize', measureGrid);
    const keydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.matches('input,select,textarea')) return;
      if (event.key === 'Escape' && selected) closePlayer();
      if (event.key === ' ' && selected) { event.preventDefault(); togglePlay(); }
      if (event.key.toLowerCase() === 'f' && selected) fullScreen();
      if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && selected) {
        event.preventDefault();
        volume = Math.max(0, Math.min(1, volume + (event.key === 'ArrowUp' ? 0.05 : -0.05)));
        if (video) video.volume = volume;
      }
      if (event.key === 'PageDown' && selected) stepChannel(1);
      if (event.key === 'PageUp' && selected) stepChannel(-1);
      if (event.key === 'm' && selected) { muted = !muted; video.muted = muted; }
      if (event.key === '/' && !selected) { event.preventDefault(); document.querySelector<HTMLInputElement>('.search-input')?.focus(); }
    };
    pipSupported = Boolean(document.pictureInPictureEnabled && video?.requestPictureInPicture);
    window.addEventListener('keydown', keydown);
    requestAnimationFrame(measureGrid);
    const colorScheme = window.matchMedia('(prefers-color-scheme: dark)');
    const updateSystemTheme = () => { if (themeMode === 'system') applyTheme('system'); };
    colorScheme.addEventListener('change', updateSystemTheme);
    return () => { colorScheme.removeEventListener('change', updateSystemTheme); window.removeEventListener('keydown', keydown); window.removeEventListener('scroll', updateScroll); window.removeEventListener('resize', measureGrid); abortController?.abort(); hls?.destroy(); };
  });
</script>

<svelte:head><title>On Air — televisión en vivo</title></svelte:head>

<div class="app-shell">
  <aside class="sidebar">
    <a class="brand" href="#inicio" aria-label="On Air, inicio"><span class="brand-mark"><Radio size={19} strokeWidth={2.4} /></span><span>on<span class="brand-accent">air</span></span><span class="brand-live"><i></i> LIVE</span></a>
    <div class="side-caption">EXPLORAR</div>
    <button class="nav-item" class:active={!guideMode && library === 'all'} onclick={() => { guideMode = false; library = 'all'; }}><Tv size={17} /><span>Todos los canales</span><span class="nav-count">{channels.length ? channels.length.toLocaleString('es') : '—'}</span></button>
    <button class="nav-item" class:active={!guideMode && library === 'favorites'} onclick={() => { guideMode = false; library = 'favorites'; }}><Star size={17} /><span>Favoritos</span><span class="nav-count">{favorites.length || ''}</span></button>
    <button class="nav-item" class:active={!guideMode && library === 'recent'} onclick={() => { guideMode = false; library = 'recent'; }}><Clock3 size={17} /><span>Vistos recientemente</span><span class="nav-count">{recentlyViewed.length || ''}</span></button>
    <button class="nav-item" class:active={guideMode} onclick={showGuide}><CalendarDays size={17} /><span>Guía por país</span></button>
    <div class="side-bottom"><div class="connection"><span class:connected={!loading && !error && !catalogCached}></span><span>{loading ? 'Conectando al catálogo' : error ? 'Sin conexión' : catalogCached ? 'Catálogo guardado' : 'Catálogo actualizado'}</span></div><div class="side-foot">IPTV ORG <span>·</span> CATÁLOGO ABIERTO</div></div>
  </aside>

  <main class="main-area" id="inicio">
    <header class="topbar"><div class="breadcrumb">BIBLIOTECA <span>/</span> <b>TELEVISIÓN EN VIVO</b></div><div class="topbar-right"><span class="source-dot"></span><span>FUENTE PÚBLICA</span><span class="top-divider"></span><kbd>/</kbd><span class="search-hint">Buscar canal</span></div><label class="theme-control" aria-label="Tema de la aplicación"><span>TEMA</span><select value={themeMode} onchange={(event) => applyTheme((event.currentTarget as HTMLSelectElement).value as 'system' | 'light' | 'dark')}><option value="system">Sistema</option><option value="dark">Oscuro</option><option value="light">Claro</option></select></label></header>
    <section class="content">
      <div class="hero-row"><div><div class="eyebrow"><span></span> {guideMode ? 'PROGRAMACIÓN TELEVISIVA' : 'TU TELEVISIÓN, EN UN SOLO LUGAR'}</div><h1>{#if guideMode}Parrilla <em>por país.</em>{:else}Encuentra algo <em>en vivo.</em>{/if}</h1><p class="intro">{guideMode ? 'Consulta lo que está al aire y abre el canal desde su programación.' : 'Explora canales de todo el mundo. Elige uno y disfruta.'}</p></div><div class="live-stat"><div class="live-stat-number">{guideMode ? (guide ? guideChannelRows.length.toLocaleString('es') : '—') : (channels.length ? channels.length.toLocaleString('es') : '—')}</div><div class="live-stat-label">{guideMode ? 'CANALES EN LA GUÍA' : 'CANALES DISPONIBLES'}</div></div></div>

      {#if guideMode}
      <section class="guide-panel" aria-label="Programación por país">
        <div class="guide-toolbar"><label class="guide-country"><span>PAÍS</span><select bind:value={guideCountry} onchange={() => { guide = null; guideError = ''; }} aria-label="País de la programación">{#each guideCountries as code}<option value={code}>{guideCountryName(code)}</option>{/each}</select></label><button class="primary-button guide-load" onclick={loadGuide} disabled={guideLoading}><RotateCw size={15} class={guideLoading ? 'spinning' : ''} />{guideLoading ? 'Cargando programación…' : guide ? 'Consultar de nuevo' : 'Cargar programación'}</button><span class="guide-window">PRÓXIMAS 24 HORAS</span></div>
        {#if guideLoading}<div class="state-panel guide-state"><div class="loader-ring"></div><h2>Cargando la guía de {guideCountryName(guideCountry)}</h2><p>Estamos leyendo la programación del país. Puede tardar unos segundos.</p></div>
        {:else if guideError}<div class="state-panel guide-state"><div class="state-icon"><Signal size={22} /></div><h2>No se pudo abrir la guía</h2><p>{guideError}</p><button class="primary-button" onclick={loadGuide}><RotateCw size={15} /> Intentar de nuevo</button></div>
        {:else if guide}
          <div class="guide-heading"><span>CANAL</span><span>PROGRAMACIÓN LOCAL · {guideCountryName(guideCountry).toLocaleUpperCase('es')}</span></div>
          {#if guideChannelRows.length === 0}<div class="state-panel guide-state"><div class="state-icon"><Tv size={22} /></div><h2>No hay canales vinculados en esta guía</h2><p>Esta parrilla no incluye canales del catálogo disponibles para reproducir.</p></div>
          {:else}<div class="guide-list">{#each guideChannelRows as row (row.channel.id)}<div class="guide-row"><button class="guide-channel" onclick={() => openChannel(row.channel)} aria-label="Ver canal {row.channel.name}"><span class="guide-logo">{#if row.channel.logo}<img src={row.channel.logo} alt="" loading="lazy" onerror={(event) => ((event.currentTarget as HTMLImageElement).hidden = true)} />{:else}<Tv size={19} />{/if}</span><span class="guide-channel-copy"><b>{row.channel.name}</b><small>{guideCountryName(row.channel.country)}</small></span><Play size={14} class="guide-play" /></button><div class="guide-programs">{#each row.programs as program (program.start + program.title)}<button class="guide-program" class:program-current={program.start <= Date.now() && program.stop > Date.now()} onclick={() => openChannel(row.channel)} title={program.description || program.title} aria-label="Ver {row.channel.name}: {program.title}, {formatGuideTime(program.start)} a {formatGuideTime(program.stop)}"><span>{formatGuideTime(program.start)} — {formatGuideTime(program.stop)}</span><b>{program.title}</b>{#if program.start <= Date.now() && program.stop > Date.now()}<i>AHORA</i>{/if}</button>{/each}</div></div>{/each}</div>{/if}
          <div class="guide-credit">Datos de programación de <a href="https://iptv-epg.org/guides" target="_blank" rel="noreferrer">IPTV-EPG.org</a>. La guía se carga bajo demanda.</div>
        {:else}<div class="guide-empty"><CalendarDays size={24} /><h2>Elige un país para ver su programación</h2><p>La guía se descarga solo cuando pulsas “Cargar programación”.</p></div>{/if}
      </section>
      {:else}
      <div class="toolbar"><label class="search-box"><Search size={18} /><input class="search-input" bind:value={searchText} placeholder="Buscar canal o alternativa..." aria-label="Buscar canal o alternativa" /><kbd>/</kbd></label><details class="country-picker"><summary aria-label="Filtrar por país">{selectedCountries.length ? `${selectedCountries.length} países` : 'PAÍS'}<ChevronDown size={13} /></summary><div class="country-menu"><input class="country-search" bind:value={countrySearch} placeholder="Buscar país..." aria-label="Buscar país" />{#if selectedCountries.length}<button class="country-clear" onclick={() => selectedCountries = []}>Limpiar selección</button>{/if}<div class="country-options">{#each visibleCountries as code}<label><input type="checkbox" checked={selectedCountries.includes(code)} onchange={(event) => toggleCountry(code, (event.currentTarget as HTMLInputElement).checked)} /><span>{countryNames.of(code) ?? code}</span><small>{code}</small></label>{/each}{#if visibleCountries.length === 0}<p>No hay países coincidentes.</p>{/if}</div></div></details><label class="filter-control category-filter"><span>CATEGORÍA</span><select bind:value={category} aria-label="Filtrar por categoría"><option value="all">Todas</option>{#each categories as item}<option value={item}>{item}</option>{/each}</select></label><details class="advanced-filter"><summary aria-label="Filtros adicionales"><span>MÁS FILTROS</span><ChevronDown size={13} /></summary><div class="advanced-menu"><label class="filter-control"><span>IDIOMA</span><select bind:value={language} aria-label="Filtrar por idioma"><option value="all">Todos</option>{#each languages as item}<option value={item}>{item}</option>{/each}</select></label><label class="filter-control"><span>CALIDAD MÍNIMA</span><select bind:value={minQuality} aria-label="Calidad mínima"><option value="all">Cualquiera</option><option value="480p">SD</option><option value="720p">720p</option><option value="1080p">1080p</option></select></label><label><input type="checkbox" bind:checked={hideGeoBlocked} /> Ocultar geo bloqueados</label><label><input type="checkbox" bind:checked={hideNon24} /> Ocultar no 24/7</label></div></details><div class="view-switch" role="group" aria-label="Formato de canales"><button class:active={!listView} onclick={() => { listView = false; requestAnimationFrame(measureGrid); }} aria-label="Vista de cuadrícula" aria-pressed={!listView}><Grid2X2 size={15} /></button><button class:active={listView} onclick={() => { listView = true; requestAnimationFrame(measureGrid); }} aria-label="Vista de lista" aria-pressed={listView}><List size={16} /></button></div><button class="refresh-button" onclick={refresh} disabled={loading} aria-label="Volver a cargar el catálogo"><RotateCw size={16} class={loading ? 'spinning' : ''} /></button></div>

      <div class="results-row"><div class="results-title">{query || selectedCountries.length > 0 || category !== 'all' || language !== 'all' || minQuality !== 'all' || hideGeoBlocked || hideNon24 ? 'RESULTADOS' : 'TODOS LOS CANALES'} <span>{filtered.length.toLocaleString('es')}</span></div><div class="catalog-status" title={catalogUpdatedAt ? `Actualizado: ${new Date(catalogUpdatedAt).toLocaleString('es')}` : ''}><Signal size={13} /> {catalogCached ? 'CATÁLOGO EN CACHÉ' : 'LISTA ACTUALIZADA'}</div></div>
      {#if loading && channels.length === 0}<div class="state-panel"><div class="loader-ring"></div><h2>Preparando tu guía</h2><p>Conectando con el catálogo mundial de canales…</p></div>
      {:else if error && channels.length === 0}<div class="state-panel"><div class="state-icon"><Signal size={22} /></div><h2>El catálogo no está disponible</h2><p>{error}</p><button class="primary-button" onclick={refresh}><RotateCw size={15} /> Intentar de nuevo</button><button class="text-button" onclick={playDemo}>Probar el reproductor con una señal de muestra</button></div>
      {:else if filtered.length === 0}<div class="state-panel"><div class="state-icon">{#if library === 'favorites'}<Star size={22} />{:else}<Search size={22} />{/if}</div><h2>{library === 'favorites' ? 'Todavía no tienes favoritos' : library === 'recent' ? 'Aún no has visto canales' : 'No encontramos ese canal'}</h2><p>{library === 'favorites' ? 'Guarda un canal con la estrella del reproductor y aparecerá aquí.' : library === 'recent' ? 'Los canales que abras aparecerán en esta lista.' : 'Prueba con otro nombre o cambia los filtros.'}</p><button class="text-button" onclick={() => { query = ''; searchText = ''; selectedCountries = []; countrySearch = ''; category = 'all'; language = 'all'; minQuality = 'all'; hideGeoBlocked = false; hideNon24 = false; library = 'all'; }}>Ver todos los canales</button></div>
      {:else}<div class="channel-grid" class:list-view={listView} bind:this={gridElement} style={`--columns:${columns};grid-template-columns:repeat(${columns},minmax(0,1fr))`}><div class="virtual-spacer" style={`height:${Math.max(0, beforeSpace - 12)}px;grid-column:1/-1`}></div>{#each visibleChannels as channel (channel.id)}<button class="channel-card" onclick={() => openChannel(channel)} aria-label="Reproducir {channel.name}"><div class="card-logo">{#if channel.logo}<img src={channel.logo} alt="" loading="lazy" onerror={(event) => ((event.currentTarget as HTMLImageElement).hidden = true)} />{:else}<span class="logo-placeholder"><Tv size={23} /></span>{/if}<span class="play-overlay"><Play size={18} fill="currentColor" /></span><span class="live-pill">TV</span></div><div class="card-info"><span class="channel-name">{channel.name}</span><span class="channel-meta">{countryNames.of(channel.country) ?? channel.country}{#if channel.categories[0]} <span>·</span> {channel.categories[0]}{/if}</span><div class="card-badges">{#if channel.streams[0]?.quality}<span>{channel.streams[0].quality}</span>{/if}{#each channel.streams[0]?.labels ?? [] as label}<span class:badge-warning={label === 'Geo-blocked'}>{label}</span>{/each}</div></div><ArrowUpRight class="card-arrow" size={15} /></button>{/each}<div class="virtual-spacer" style={`height:${Math.max(0, afterSpace - 12)}px;grid-column:1/-1`}></div></div>{/if}
      <footer class="page-footer"><span>ON AIR <span class="footer-dot">·</span> CANALES DE TELEVISIÓN EN ABIERTO</span><span>Los canales y streams son proporcionados por IPTV-org.</span></footer>
      {/if}
    </section>
  </main>
</div>

{#if selected}<div class="player-backdrop" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) closePlayer(); }}><section class="player-modal" class:player-expanded={playerExpanded} role="dialog" aria-modal="true" aria-label="Reproductor de {selected.name}"><div class="player-top"><button class="player-back" onclick={closePlayer}><ChevronLeft size={17} /> VOLVER A CANALES</button><div class="player-channel-name"><span class="player-live"><i></i> EN VIVO</span>{selected.name}</div><button class="close-button" onclick={closePlayer} aria-label="Cerrar reproductor"><X size={18} /></button></div><div class="video-wrap"><video bind:this={video} autoplay playsinline onplay={() => playing = true} onpause={() => playing = false} onvolumechange={() => muted = video.muted} onenterpictureinpicture={() => pipActive = true} onleavepictureinpicture={() => pipActive = false} onerror={() => { if (!video.currentSrc) return; if (selected && currentStream + 1 < selected.streams.length) { currentStream += 1; playStream(); } else if (selected) { playError = 'Canal no disponible. Prueba otro canal.'; } }}></video>{#if playError}<div class="video-error"><div class="error-mark"><Signal size={24} /></div><b>Señal no disponible</b><span>{playError}</span>{#if currentStream + 1 < selected.streams.length}<button class="primary-button" onclick={() => { currentStream += 1; playError = ''; playStream(); }}><RotateCw size={15} /> Probar siguiente señal</button>{/if}</div>{:else if !playing}<div class="video-loading"><div class="loader-ring"></div><span>CONECTANDO CON LA SEÑAL</span></div>{/if}<div class="video-corner"><span><i></i> EN VIVO</span></div></div><div class="player-controls"><div class="control-group"><button onclick={togglePlay} aria-label={playing ? 'Pausar' : 'Reproducir'}>{#if playing}<Pause size={17} />{:else}<Play size={17} />{/if}</button><button onclick={() => { muted = !muted; video.muted = muted; }} aria-label={muted ? 'Activar sonido' : 'Silenciar'}>{#if muted}<VolumeX size={18} />{:else}<Volume2 size={18} />{/if}</button><input class="volume-slider" type="range" min="0" max="1" step="0.05" value={volume} oninput={setVolume} aria-label="Volumen" /></div><div class="control-channel"><span>{selected.name}</span>{#if availableQualities.length > 0}<label class="quality-select"><span>CALIDAD</span><select bind:value={qualityLevel} onchange={selectQuality} aria-label="Calidad de reproducción"><option value={-1}>Auto</option>{#each availableQualities as quality (quality.index)}<option value={quality.index}>{quality.label}</option>{/each}</select></label>{:else}<small>{selected.streams[currentStream]?.quality ?? 'SEÑAL EN VIVO'}</small>{/if}</div><div class="control-group right">{#if pipSupported}<button class:pip-active={pipActive} onclick={togglePictureInPicture} aria-label={pipActive ? 'Salir de Picture-in-Picture' : 'Picture-in-Picture'} title="Picture-in-Picture"><PictureInPicture2 size={17} /></button>{/if}<button class:favorite-active={favorites.includes(selected.id)} onclick={() => toggleFavorite(selected!.id)} aria-label={favorites.includes(selected.id) ? 'Quitar de favoritos' : 'Añadir a favoritos'} title={favorites.includes(selected.id) ? 'Quitar de favoritos' : 'Añadir a favoritos'}><Star size={17} fill={favorites.includes(selected.id) ? 'currentColor' : 'none'} /></button><button onclick={() => stepChannel(-1)} aria-label="Canal anterior"><ChevronLeft size={20} /></button><button onclick={() => stepChannel(1)} aria-label="Canal siguiente"><ChevronRight size={20} /></button><button onclick={() => playerExpanded = !playerExpanded} aria-label={playerExpanded ? 'Reducir reproductor' : 'Expandir reproductor a la ventana'} title={playerExpanded ? 'Reducir reproductor' : 'Expandir a la ventana'}>{#if playerExpanded}<Minimize2 size={17} />{:else}<Maximize2 size={17} />{/if}</button><button onclick={fullScreen} aria-label="Pantalla completa" title="Pantalla completa"><Maximize size={17} /></button></div></div><div class="player-tip"><span>ATAJOS</span> ESPACIO <span>REPRODUCIR</span><b>·</b> ↑/↓ <span>VOLUMEN</span><b>·</b> F <span>PANTALLA COMPLETA</span><b>·</b> ESC <span>CERRAR</span></div></section></div>{/if}
