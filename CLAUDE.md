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
  `mykvstore` param (see kvstore/SECURITY.md).
