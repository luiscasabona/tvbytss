export interface ApiChannel {
  id: string;
  name: string;
  alt_names?: string[];
  country: string;
  categories?: string[];
  is_nsfw?: boolean;
  closed?: string | null;
}

export interface ApiStream {
  channel: string | null;
  url: string;
  quality?: string;
  labels?: string[];
  referrer?: string;
  user_agent?: string;
}

export interface ApiLogo {
  channel: string;
  url: string;
  in_use?: boolean;
}

export interface ApiFeed {
  channel?: string;
  languages?: string[];
}

export interface Channel {
  id: string;
  name: string;
  altNames: string[];
  country: string;
  categories: string[];
  languages: string[];
  logo?: string;
  streams: ApiStream[];
}

export interface CatalogResult {
  channels: Channel[];
  cached: boolean;
  updatedAt: number;
}

export interface GuideProgram {
  channelId: string;
  title: string;
  description: string;
  start: number;
  stop: number;
}

export interface CountryGuide {
  country: string;
  date: string;
  cached: boolean;
  updatedAt: number;
  programs: GuideProgram[];
}

export async function loadCountryGuide(country: string): Promise<CountryGuide> {
  const code = country.toLowerCase();
  // The backend owns the shared per-country, per-day cache. A manual reload in
  // the client still asks for the guide, but does not bypass that daily policy.
  const response = await fetch(`${apiBase}/api/v1/guides?country=${encodeURIComponent(code)}`);
  if (!response.ok) throw new Error(`La guía respondió ${response.status}`);
  return await response.json() as CountryGuide;
}

const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const localCatalogDb = 'on-air-server-catalog-v1';

async function readLocalCatalog(): Promise<CatalogResult | undefined> {
  try {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(localCatalogDb, 1);
      request.onupgradeneeded = () => request.result.createObjectStore('catalog');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return await new Promise((resolve, reject) => {
      const request = db.transaction('catalog', 'readonly').objectStore('catalog').get('latest');
      request.onsuccess = () => { db.close(); resolve(request.result as CatalogResult | undefined); };
      request.onerror = () => { db.close(); reject(request.error); };
    });
  } catch { return undefined; }
}

async function writeLocalCatalog(catalog: CatalogResult): Promise<void> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(localCatalogDb, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('catalog');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction('catalog', 'readwrite');
    transaction.objectStore('catalog').put(catalog, 'latest');
    transaction.oncomplete = () => { db.close(); resolve(); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  });
}

export async function loadChannels(signal?: AbortSignal): Promise<CatalogResult> {
  // Catalogue freshness is managed centrally by the backend.
  try {
    const response = await fetch(`${apiBase}/api/v1/channels`, { signal });
    if (!response.ok) throw new Error(`El backend respondió ${response.status}`);
    const result = await response.json() as CatalogResult;
    try { await writeLocalCatalog(result); } catch { /* La copia local solo es un respaldo. */ }
    return result;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    const cached = await readLocalCatalog();
    if (cached) return { ...cached, cached: true };
    throw error;
  }
}
