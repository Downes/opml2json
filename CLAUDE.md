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

## Auth
- Write/admin endpoints (`/fetch_feed`, `/admin/settings`) require
  `Authorization: Bearer <token>`.
- Token verification is local JWT/JWKS ("Pattern B") via the shared
  `clist-kvstore-auth` package (`clist_kvstore_auth.asyncio`), pinned by
  commit SHA in `requirements.txt` (github.com/Downes/clist-kvstore-auth),
  `_verify_identity()` in `hello.py`. A JWT's own `iss` claim names the
  instance that signed it; we fetch *that* instance's
  `/.well-known/jwks.json` and verify the signature — open to any issuer,
  no allowlist (anyone can run their own kvstore and interoperate). The
  client's `X-Kvstore-Url` header is ignored for real JWTs — `iss` is
  tamper-proof and already says where to verify, so trusting a
  client-supplied hint on top would add nothing.
- Opaque (pre-migration) tokens carry no `iss` and can't be verified
  locally, so they still fall back to the callback
  (`GET {X-Kvstore-Url}/auth/verify`) — but *only* when `X-Kvstore-Url` is
  in `ALLOWED_KVSTORE_URLS`. This app is unusual among the migrated apps in
  genuinely supporting more than one trusted kvstore instance (not just a
  single `KVSTORE_URL`), and `kvstore_url` here is client-supplied, driving
  a server-side request that carries the caller's own Bearer token — without
  this allowlist it's an SSRF + token-forwarding primitive to an arbitrary
  HTTPS host (same class of issue fixed in kvstore's `mykvstore` param, see
  kvstore/SECURITY.md). This app has no ownership model (no per-user
  content, just shared feed caching), so no qualified-identity/`owns()`
  logic is needed here — `Identity.username` is used directly wherever a
  verified caller is needed, and `ALLOWED_KVSTORE_URLS` only gates the
  opaque-token fallback and admin issuer-trust (see below).
- `/admin/settings` is additionally gated by a locally-reimplemented
  `_is_admin(identity)` in `hello.py`, not `clist_kvstore_auth.asyncio.is_admin()`
  or `clist_server_admin.redis.is_admin()` directly, because
  `ALLOWED_KVSTORE_URLS` is DB-overridable here (not just a static env var)
  and neither shared package's own `is_admin()` checks a DB override.

## Environment variables
- ALLOWED_KVSTORE_URLS — comma-separated kvstore instances trusted for
  `ADMIN_USERNAMES` admin access, and allowed as the opaque-token fallback
  verification target (default: https://kvstore.mooc.ca,https://kvstore.downes.ca).
  Does NOT gate ordinary token verification, which is local JWT/JWKS and
  open to any issuer — see Auth above. Can be overridden at runtime by an
  admin via `/admin/settings` — see below; the env var is only the fallback
  default used until an override is saved.
- ADMIN_USERNAMES — comma-separated usernames allowed to call `/admin/settings`
  (currently `downes`).

## Admin settings
Generic admin-editable runtime settings — imported from the shared
`clist-server-admin` package (`clist_server_admin.redis`), pinned by commit
SHA in `requirements.txt` (github.com/Downes/clist-server-admin, `[redis]`
extra). No local `admin_settings.py` copy anymore. This app has no SQL
database — settings are stored in a single Redis hash (`HSET admin_settings
<key> <value>`) in the same Redis instance already used for feed caching
(`appendonly yes`, so it survives a container restart).

- `GET /admin/settings` / `PUT /admin/settings` — Bearer token in
  `Authorization` (same manual-header-parsing style as `/fetch_feed` — this
  app has no FastAPI `Depends()`/`Header()` usage, so the admin routes
  don't introduce one), verified via `_verify_identity()` (Pattern B, see
  Auth above). 401 if the token doesn't verify, 403 if `_is_admin()` says
  no (wrong username, or right username from an untrusted issuer), 400 on
  an unknown key.
- Currently two fields: `ENABLED` (boolean, default `true`) and
  `ALLOWED_KVSTORE_URLS` (non-sensitive). An admin override of
  `ALLOWED_KVSTORE_URLS` takes effect immediately, no restart — `_is_admin()`
  and the opaque-token fallback in `_verify_identity()` both read it fresh
  via `_allowed_kvstore_urls()` on every call, falling back to the
  `ALLOWED_KVSTORE_URLS` env var if no override has been saved.
- `ENABLED` is a kill switch, implemented as a second `@app.middleware("http")`
  function (`_enabled_gate`, alongside the existing `CORSMiddleware`) that
  returns `503 {"error": "Service temporarily disabled by administrator"}`
  for every path except `/admin/settings` when set to `false`. This app has
  no `/health` route, so `/admin/settings` is the only exemption.
- Caution: since `ALLOWED_KVSTORE_URLS` is the trusted-admin-issuer set,
  saving a bad value here can lock the admin out of `/admin/settings`
  itself (ordinary callers are unaffected — their JWT verification is open
  to any issuer regardless of this setting). Recovery doesn't need a
  restart — just a direct Redis write from the redis container itself (the
  opml2json container has no `redis-cli`): `docker exec opml2json-redis-1
  redis-cli HSET admin_settings ALLOWED_KVSTORE_URLS
  "https://kvstore.mooc.ca,https://kvstore.downes.ca"`.
