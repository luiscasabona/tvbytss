#!/usr/bin/env python3
"""On Air shared API: public channel catalogue and daily, on-demand XMLTV guides."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ON_AIR_DB", ROOT / "data/on-air.sqlite3"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
CATALOG_TTL = int(os.environ.get("CATALOG_REFRESH_SECONDS", "43200"))
API_ORIGINS = {origin.strip() for origin in os.environ.get("CORS_ORIGINS", "*").split(",") if origin.strip()}
SOURCE_API = "https://iptv-org.github.io/api"
GUIDE_URL = "https://iptv-epg.org/files/epg-{country}.xml"
RESOURCES = ("channels", "streams", "logos", "feeds", "blocklist", "categories", "countries", "languages")
CATALOG_SYNC_LOCK = threading.Lock()
GUIDE_LOCKS: dict[str, threading.Lock] = {}
GUIDE_LOCKS_LOCK = threading.Lock()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS catalog (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                updated_at INTEGER NOT NULL,
                channels_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guide_imports (
                country TEXT NOT NULL,
                utc_date TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                programs_json TEXT NOT NULL,
                PRIMARY KEY (country, utc_date)
            );
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT ''
            );
        """)


def get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "OnAir/1.0 (+catalog importer)", "Accept": "application/json, application/xml, text/xml"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"Fuente {url} respondió {response.status}")
        return json.loads(response.read())


def merge_catalog(data: dict[str, list[dict]]) -> list[dict]:
    blocked = {row.get("channel") for row in data["blocklist"]}
    streams: dict[str, list[dict]] = {}
    for row in data["streams"]:
        channel_id = row.get("channel")
        if channel_id and row.get("url"):
            streams.setdefault(channel_id, []).append({
                "channel": channel_id, "url": row["url"], "quality": row.get("quality"),
                "labels": row.get("labels", []), "referrer": row.get("referrer"), "user_agent": row.get("user_agent"),
            })
    logos: dict[str, str] = {}
    for row in sorted(data["logos"], key=lambda item: bool(item.get("in_use")), reverse=True):
        if row.get("channel") and row.get("url"):
            logos.setdefault(row["channel"], row["url"])
    languages: dict[str, set[str]] = {}
    for row in data["feeds"]:
        if row.get("channel"):
            languages.setdefault(row["channel"], set()).update(row.get("languages") or [])
    def rank(stream: dict) -> int:
        match = re.search(r"(\d{3,4})p", stream.get("quality") or "", re.I)
        return int(match.group(1)) if match else 0
    result = []
    for channel in data["channels"]:
        channel_id = channel.get("id")
        channel_streams = sorted(streams.get(channel_id, []), key=rank, reverse=True)
        if not channel_id or channel.get("closed") is not None or channel.get("is_nsfw") or channel_id in blocked or not channel_streams:
            continue
        result.append({
            "id": channel_id, "name": channel.get("name", channel_id), "altNames": channel.get("alt_names") or [],
            "country": channel.get("country", ""), "categories": channel.get("categories") or [],
            "languages": sorted(languages.get(channel_id, set())), "logo": logos.get(channel_id), "streams": channel_streams,
        })
    return sorted(result, key=lambda item: item["name"].casefold())


def sync_catalog() -> dict:
    started = int(time.time() * 1000)
    with connect() as db:
        cursor = db.execute("INSERT INTO sync_runs(started_at, status) VALUES (?, 'running')", (started,))
        run_id = cursor.lastrowid
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(RESOURCES)) as pool:
            rows = list(pool.map(lambda name: get_json(f"{SOURCE_API}/{name}.json"), RESOURCES))
        data = dict(zip(RESOURCES, rows))
        if any(not isinstance(data[name], list) for name in RESOURCES):
            raise ValueError("La fuente devolvió un conjunto de datos inválido")
        channels = merge_catalog(data)
        updated = int(time.time() * 1000)
        with connect() as db:
            db.execute("INSERT INTO catalog(singleton, updated_at, channels_json) VALUES (1, ?, ?) ON CONFLICT(singleton) DO UPDATE SET updated_at=excluded.updated_at, channels_json=excluded.channels_json", (updated, json.dumps(channels, ensure_ascii=False)))
            db.execute("UPDATE sync_runs SET finished_at=?, status='ok', message=? WHERE id=?", (updated, f"{len(channels)} canales", run_id))
        return {"updatedAt": updated, "count": len(channels)}
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE sync_runs SET finished_at=?, status='error', message=? WHERE id=?", (int(time.time() * 1000), str(exc)[:1000], run_id))
        raise


def catalog_snapshot() -> dict:
    with CATALOG_SYNC_LOCK:
        with connect() as db:
            row = db.execute("SELECT updated_at, channels_json FROM catalog WHERE singleton=1").fetchone()
        expired = row is None or (int(time.time() * 1000) - row["updated_at"] > CATALOG_TTL * 1000)
        did_refresh = False
        if expired:
            try:
                sync_catalog()
                did_refresh = True
            except Exception:
                if row is None:
                    raise
            with connect() as db:
                row = db.execute("SELECT updated_at, channels_json FROM catalog WHERE singleton=1").fetchone()
    return {"channels": json.loads(row["channels_json"]), "cached": not did_refresh, "updatedAt": row["updated_at"]}


def xmltv_timestamp(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+-]\d{4}|Z)?\s*", value)
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    zone = zone or "Z"
    sign = 1 if zone[0] == "+" else -1
    tz = dt.timezone.utc if zone == "Z" else dt.timezone(dt.timedelta(hours=sign * int(zone[1:3]), minutes=sign * int(zone[4:])))
    return int(dt.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), tzinfo=tz).timestamp() * 1000)


def guide_lock(country: str) -> threading.Lock:
    with GUIDE_LOCKS_LOCK:
        return GUIDE_LOCKS.setdefault(country, threading.Lock())


def load_guide(country: str) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    with guide_lock(country):
        with connect() as db:
            row = db.execute("SELECT updated_at, programs_json FROM guide_imports WHERE country=? AND utc_date=?", (country, today)).fetchone()
        if row:
            return {"country": country.upper(), "date": today, "updatedAt": row["updated_at"], "cached": True, "programs": json.loads(row["programs_json"])}
        request = urllib.request.Request(GUIDE_URL.format(country=country), headers={"User-Agent": "OnAir/1.0", "Accept": "application/xml, text/xml"})
        with urllib.request.urlopen(request, timeout=60) as response:
            xml_bytes = response.read()
        root = ET.fromstring(xml_bytes)
        now = int(time.time() * 1000)
        horizon = now + 24 * 60 * 60 * 1000
        programs = []
        for item in root.findall("programme"):
            start = xmltv_timestamp(item.get("start", ""))
            stop = xmltv_timestamp(item.get("stop", ""))
            channel_id = item.get("channel", "")
            title_node = item.find("title")
            title = (title_node.text or "").strip() if title_node is not None else ""
            if not channel_id or not title or start is None or stop is None or stop <= now - 2 * 60 * 60 * 1000 or start > horizon:
                continue
            description_node = item.find("desc")
            programs.append({"channelId": channel_id, "title": title, "description": (description_node.text or "").strip() if description_node is not None else "", "start": start, "stop": stop})
        programs.sort(key=lambda item: item["start"])
        updated = int(time.time() * 1000)
        with connect() as db:
            db.execute("INSERT INTO guide_imports(country, utc_date, updated_at, programs_json) VALUES (?, ?, ?, ?) ON CONFLICT(country, utc_date) DO UPDATE SET updated_at=excluded.updated_at, programs_json=excluded.programs_json", (country, today, updated, json.dumps(programs, ensure_ascii=False)))
        return {"country": country.upper(), "date": today, "updatedAt": updated, "cached": False, "programs": programs}


def periodic_sync() -> None:
    while True:
        time.sleep(max(300, CATALOG_TTL))
        try:
            catalog_snapshot()
        except Exception as exc:
            print(f"catalog sync failed: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "OnAirAPI/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, status: int, payload: object) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "public, max-age=300" if status == 200 else "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def cors(self) -> None:
        origin = self.headers.get("Origin")
        if "*" in API_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in API_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def _send(self, status: int, payload: object) -> None:
        # CORS headers must be set before headers are committed by end_headers.
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "public, max-age=300" if status == 200 else "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send(200, {"status": "ok"})
            elif parsed.path == "/api/v1/channels":
                self._send(200, catalog_snapshot())
            elif parsed.path == "/api/v1/guides":
                country = query.get("country", [""])[0].lower()
                if not re.fullmatch(r"[a-z]{2}", country):
                    self._send(400, {"error": "Se requiere un código de país ISO de dos letras"})
                    return
                self._send(200, load_guide(country))
            elif parsed.path == "/api/v1/status":
                with connect() as db:
                    row = db.execute("SELECT updated_at, length(channels_json) AS bytes FROM catalog WHERE singleton=1").fetchone()
                    run = db.execute("SELECT started_at, finished_at, status, message FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
                self._send(200, {"catalog": dict(row) if row else None, "lastSync": dict(run) if run else None})
            else:
                self._send(404, {"error": "Ruta no encontrada"})
        except urllib.error.HTTPError as exc:
            self._send(502, {"error": f"Fuente externa respondió {exc.code}"})
        except Exception as exc:
            self._send(503, {"error": str(exc)[:500]})

def main() -> None:
    initialize()
    # Start with a current catalogue, while retaining stale data when the source is down.
    def initial_sync() -> None:
        try:
            catalog_snapshot()
        except Exception as exc:
            print(f"initial catalog sync failed: {exc}", flush=True)
    threading.Thread(target=initial_sync, daemon=True, name="initial-catalog-sync").start()
    threading.Thread(target=periodic_sync, daemon=True, name="catalog-sync").start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"On Air API listening on {HOST}:{PORT}; database: {DB_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
