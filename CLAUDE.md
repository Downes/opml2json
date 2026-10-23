# opml2json (/srv/apps/opml2json)

## Overview
Python/FastAPI app: converts OPML to JSON, aggregates RSS feeds.
GitHub: https://github.com/Downes/opml2json

## Container
- Name: opml2json-opml2json-1  Port: 8000
- Runs via uvicorn (migrated from Flask/gunicorn 2026-09).

## Redis
A `redis` service (redis:7-alpine, `appendonly yes`) backs feed caching —
volume `redis_data`, internal-only network. Caches parsed feed items for
`CACHE_TTL` (1h) with ETag/Last-Modified conditional refetch, and tracks
per-feed error state with exponential backoff. Treat as a cache, not a
system of record — feeds re-fetch and repopulate it if lost.

## Entry Points
- wsgi.py — WSGI entry (legacy, may be unused now that uvicorn runs hello:app directly)
- hello.py — main app (FastAPI)

## Environment variables
- ALLOWED_KVSTORE_URLS — comma-separated kvstore instances `/fetch_feed` is
  allowed to verify a caller's Bearer token against (default:
  https://kvstore.mooc.ca,https://kvstore.downes.ca). The caller supplies
  `kvstore_url` via the `X-Kvstore-Url` header; `_verify_token()` in hello.py
  makes a server-side request to `<kvstore_url>/auth/verify` carrying that
  token. Without this allowlist it's an SSRF + token-forwarding primitive to
  an arbitrary HTTPS host — same class of issue fixed in kvstore's
  `mykvstore` param (see kvstore/SECURITY.md). Can be overridden at runtime
  by an admin via `/admin/settings` — see below; the env var is only the
  fallback default used until an override is saved.
- ADMIN_USERNAMES — comma-separated usernames allowed to call `/admin/settings`
  (currently `downes`).

## Admin settings
Part of the repo-wide Generic Admin-Editable Settings Pattern (see
`/srv/shared/admin_settings_redis.py` for the canonical reference copy of
this app's variant). This app has no SQL database — settings are stored in
a single Redis hash (`HSET admin_settings <key> <value>`) in the same Redis
instance already used for feed caching (`appendonly yes`, so it survives a
container restart).

- `GET /admin/settings` / `PUT /admin/settings` — Bearer token in
  `Authorization`, kvstore instance to verify it against in `X-Kvstore-Url`
  (same manual-header-parsing style as `/fetch_feed` — this app has no
  FastAPI `Depends()`/`Header()` usage, so the admin routes don't introduce
  one). 401 if the token doesn't verify, 403 if the verified username isn't
  in `ADMIN_USERNAMES`, 400 on an unknown key.
- Currently two fields: `ENABLED` (boolean, default `true`) and
  `ALLOWED_KVSTORE_URLS` (non-sensitive). An admin override of
  `ALLOWED_KVSTORE_URLS` takes effect immediately, no restart —
  `_verify_token()` reads it fresh via `_allowed_kvstore_urls()` on every
  call, falling back to the `ALLOWED_KVSTORE_URLS` env var if no override
  has been saved.
- `ENABLED` is a kill switch, implemented as a second `@app.middleware("http")`
  function (`_enabled_gate`, alongside the existing `CORSMiddleware`) that
  returns `503 {"error": "Service temporarily disabled by administrator"}`
  for every path except `/admin/settings` when set to `false`. This app has
  no `/health` route, so `/admin/settings` is the only exemption.
- `_verify_token()` now returns the verified username (or `None`) instead of
  a bare `bool`, so `/admin/settings` can check it against `ADMIN_USERNAMES`.
  `/fetch_feed`'s existing `if not await _verify_token(...)` check still
  works unchanged against the new return type.
- Caution: since `ALLOWED_KVSTORE_URLS` gates which kvstore can authenticate
  *any* caller including the admin, saving a bad value here can lock the
  admin out too. Recovery doesn't need a restart — just a direct Redis
  write from the redis container itself (the opml2json container has no
  `redis-cli`): `docker exec opml2json-redis-1 redis-cli HSET
  admin_settings ALLOWED_KVSTORE_URLS
  "https://kvstore.mooc.ca,https://kvstore.downes.ca"`.
