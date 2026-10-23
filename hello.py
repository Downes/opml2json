import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import aiohttp
import feedparser
import listparser
import redis.asyncio as aioredis
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from admin_settings import (
    SettingField,
    get_setting,
    is_admin,
    register_admin_settings_routes,
)

CACHE_TTL = 3600
USER_AGENT = "Mozilla/5.0 (compatible; opml2json/2.0)"

# kvstore instances /fetch_feed is allowed to verify a caller's token against.
# kvstore_url is client-supplied (X-Kvstore-Url header) and drives a server-side
# request that carries the caller's own Bearer token — without this allowlist
# it's an SSRF + token-forwarding primitive to an arbitrary HTTPS host.
# Fallback default; overridden by admin_settings.ALLOWED_KVSTORE_URLS once an
# admin saves one via /admin/settings (see _allowed_kvstore_urls()).
ALLOWED_KVSTORE_URLS_DEFAULT = os.environ.get(
    "ALLOWED_KVSTORE_URLS", "https://kvstore.mooc.ca,https://kvstore.downes.ca"
)

redis_client: aioredis.Redis = None


def get_redis() -> aioredis.Redis:
    return redis_client


async def _allowed_kvstore_urls() -> list[str]:
    raw = await get_setting(get_redis, "ALLOWED_KVSTORE_URLS", default=ALLOWED_KVSTORE_URLS_DEFAULT)
    return [u.strip() for u in raw.split(",") if u.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    for attempt in range(5):
        try:
            redis_client = aioredis.from_url("redis://redis:6379", decode_responses=True)
            await redis_client.ping()
            break
        except Exception as e:
            if attempt == 4:
                raise RuntimeError(f"Redis unavailable after 5 attempts: {e}")
            await asyncio.sleep(2 ** attempt)
    yield
    await redis_client.aclose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _verify_token(token: str, kvstore_url: str) -> Optional[str]:
    """Verify a Bearer token against kvstore_url. Returns the username on
    success, or None — callers that only need a yes/no check can still use
    this directly in a boolean context (`if not await _verify_token(...)`)."""
    if not token or not kvstore_url:
        return None
    if kvstore_url not in await _allowed_kvstore_urls():
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                kvstore_url.rstrip("/") + "/auth/verify",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if not resp.ok:
                    return None
                data = await resp.json()
                return (data or {}).get("username") or None
    except Exception:
        return None


async def _require_admin(request: Request):
    """Mirrors fetch_feed's manual header parsing. Returns (username, None)
    on success, or (None, (body, status)) on failure."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    kvstore_url = request.headers.get("X-Kvstore-Url", "").strip()
    username = await _verify_token(token, kvstore_url)
    if not username:
        return None, ({"error": "Unauthorized"}, 401)
    if not is_admin(username):
        return None, ({"error": "Forbidden"}, 403)
    return username, None


SETTINGS_SCHEMA = [
    SettingField(
        "ENABLED", "Enabled", "boolean", False, None,
        "When off, this app's functional endpoints return 503. /admin/settings "
        "stays reachable so you can turn it back on.",
    ),
    SettingField(
        "ALLOWED_KVSTORE_URLS", "Allowed KVStore URLs", "text", False, None,
        "Comma-separated kvstore instances allowed to issue tokens for this app "
        "(checked against the client's X-Kvstore-Url header on every request).",
    ),
]
SETTINGS_DEFAULTS = {"ENABLED": "true", "ALLOWED_KVSTORE_URLS": ALLOWED_KVSTORE_URLS_DEFAULT}

register_admin_settings_routes(app, SETTINGS_SCHEMA, get_redis, _require_admin, SETTINGS_DEFAULTS)


@app.middleware("http")
async def _enabled_gate(request: Request, call_next):
    if request.url.path == "/admin/settings":
        return await call_next(request)
    if await get_setting(get_redis, "ENABLED", default="true") == "false":
        return JSONResponse({"error": "Service temporarily disabled by administrator"}, status_code=503)
    return await call_next(request)


def _parse_feed(content: bytes) -> feedparser.FeedParserDict:
    return feedparser.parse(content)


def _extract_did(feed: feedparser.FeedParserDict) -> Optional[str]:
    """Extract a did:web DID from feed entries or channel metadata.

    Item-level DIDs take priority (more specific — correct for multi-author feeds).
    Channel-level is the fallback for feeds where only the channel carries a DID.
    """
    # Item-level: first entry with a DID author link or Atom author URI
    for entry in feed.entries:
        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if link.get("rel") == "author" and href.startswith("did:"):
                return href
        detail = getattr(entry, "author_detail", {}) or {}
        href = detail.get("href", "")
        if href.startswith("did:"):
            return href
    # Channel-level fallback: atom:link rel="author"
    for link in getattr(feed.feed, "links", []):
        href = link.get("href", "")
        if link.get("rel") == "author" and href.startswith("did:"):
            return href
    # Channel-level fallback: Atom <author><uri>
    detail = getattr(feed.feed, "author_detail", {}) or {}
    href = detail.get("href", "")
    if href.startswith("did:"):
        return href
    return None


def _parse_opml(content: str):
    return listparser.parse(content)


def _entry_to_item(entry, feed_title: str, feed_url: str) -> dict:
    item = {
        "guid":         entry.get("id") or entry.get("link") or "",
        "title":        entry.get("title"),
        "link":         entry.get("link"),
        "author":       entry.get("author", ""),
        "published":    entry.get("published"),
        "summary":      entry.get("summary", ""),
        "source":       feed_title or feed_url,
        "full_content": None,
    }
    if entry.get("content"):
        item["full_content"] = entry.content[0].value
    elif entry.get("description"):
        item["full_content"] = entry.get("description")
    try:
        dt = datetime(*entry.published_parsed[:6]) if entry.get("published_parsed") else None
        item["published_ts"] = int(dt.timestamp()) if dt else int(time.time())
    except (ValueError, OverflowError):
        item["published_ts"] = int(time.time())
    if entry.get("enclosures"):
        audio = [e["href"] for e in entry.enclosures
                 if (e.get("type") or "").startswith("audio/")]
        if audio:
            item["audio"] = audio
    return item


async def _record_error(errors_key: str, error_msg: str) -> None:
    errors_raw = await redis_client.get(errors_key)
    state = json.loads(errors_raw) if errors_raw else {"consecutive_errors": 0}
    n = state["consecutive_errors"] + 1
    backoff = min(60 * (1 << (n - 1)), 86400)  # 60s, 120s, 240s … capped at 24h
    await redis_client.setex(errors_key, 86400 * 2, json.dumps({
        "consecutive_errors": n,
        "last_error":         error_msg,
        "last_error_time":    int(time.time()),
        "backoff_until":      int(time.time()) + backoff,
    }))


async def _clear_errors(errors_key: str) -> None:
    await redis_client.delete(errors_key)


async def _fetch_and_cache(url: str) -> dict:
    """Fetch a feed, parse it, cache in Redis for 1 hour.

    Uses ETag/Last-Modified for conditional requests — a 304 extends the TTL
    without re-fetching content. Tracks per-feed errors with exponential backoff
    so failing feeds are not retried aggressively. Falls back to stale cached data
    when available. Returns {"title": str, "items": [...], "stale"?: bool, "error"?: str}.
    """
    cache_key  = "feed:"        + hashlib.sha256(url.encode()).hexdigest()
    errors_key = "feed_errors:" + hashlib.sha256(url.encode()).hexdigest()

    cached_raw = await redis_client.get(cache_key)
    cached = json.loads(cached_raw) if cached_raw else None

    # Honour backoff window — don't hammer failing feeds
    errors_raw = await redis_client.get(errors_key)
    if errors_raw:
        err_state = json.loads(errors_raw)
        if time.time() < err_state.get("backoff_until", 0):
            if cached:
                return {"title": cached["title"], "items": cached["items"],
                        "stale": True, "error": err_state.get("last_error", "")}
            raise Exception(f"Feed unavailable (in backoff): {err_state.get('last_error', '')}")

    headers = {"User-Agent": USER_AGENT}
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        elif cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 304 and cached:
                    await redis_client.expire(cache_key, CACHE_TTL)
                    await _clear_errors(errors_key)
                    return {"title": cached["title"], "items": cached["items"],
                            "author_did": cached.get("author_did")}
                resp.raise_for_status()
                content = await resp.read()
                etag = resp.headers.get("ETag")
                last_modified = resp.headers.get("Last-Modified")
    except Exception as e:
        await _record_error(errors_key, str(e))
        if cached:
            return {"title": cached["title"], "items": cached["items"],
                    "author_did": cached.get("author_did"),
                    "stale": True, "error": str(e)}
        raise

    feed = await asyncio.get_running_loop().run_in_executor(None, _parse_feed, content)
    feed_title = (feed.feed.get("title") or "").strip()
    items = [_entry_to_item(entry, feed_title, url) for entry in feed.entries]
    author_did = _extract_did(feed)

    await redis_client.setex(cache_key, CACHE_TTL, json.dumps({
        "title": feed_title,
        "items": items,
        "author_did": author_did,
        "etag": etag,
        "last_modified": last_modified,
    }))
    await _clear_errors(errors_key)
    return {"title": feed_title, "items": items, "author_did": author_did}


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <h1>Welcome to the OPML2JSON Service</h1>
    <form action="/upload_opml" method="post" enctype="multipart/form-data">
        <label>OPML file: <input type="file" name="file" accept=".opml"></label><br><br>
        <label>Or URL: <input type="url" name="url" placeholder="https://example.com/feeds.opml"></label><br><br>
        <label>Cursor: <input type="text" name="cursor" placeholder="1698790400.0"></label><br><br>
        <label>Limit: <input type="number" name="limit" value="20" min="1"></label><br><br>
        <button type="submit">Submit</button>
    </form>
    """


@app.post("/upload_opml")
async def upload_opml(
    file:   Optional[UploadFile] = File(None),
    url:    Optional[str]        = Form(None),
    cursor: Optional[str]        = Form(None),
    limit:  int                  = Form(20),
):
    cursor_ts = float(cursor) if cursor else None
    if not file and not url:
        return JSONResponse({"error": "No file or URL provided"}, status_code=400)
    try:
        if file:
            content = (await file.read()).decode("utf-8")
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if not resp.ok:
                        return JSONResponse(
                            {"error": f"Failed to fetch OPML: {resp.status}"}, status_code=400)
                    content = await resp.text()

        result = await asyncio.get_running_loop().run_in_executor(None, _parse_opml, content)
        if result.bozo:
            raise ValueError(f"Error parsing OPML: {result.bozo_exception}")

        rss_urls = [f.url for f in result.feeds if f.url]
        if not rss_urls:
            return JSONResponse({"error": "No RSS URLs found in the OPML file"}, status_code=400)

        fetched = await asyncio.gather(
            *[_fetch_and_cache(u) for u in rss_urls],
            return_exceptions=True,
        )

        all_items = []
        for feed_result in fetched:
            if isinstance(feed_result, Exception):
                continue
            all_items.extend(feed_result["items"])

        all_items.sort(key=lambda x: x.get("published_ts", 0), reverse=True)
        if cursor_ts:
            all_items = [i for i in all_items if i.get("published_ts", 0) < cursor_ts]
        paginated = all_items[:limit]
        next_cursor = all_items[limit]["published_ts"] if len(all_items) > limit else None
        return {"items": paginated, "next_cursor": next_cursor}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/list_feeds")
async def list_feeds(
    url:  Optional[str]        = Form(None),
    file: Optional[UploadFile] = File(None),
):
    if not file and not url:
        return JSONResponse({"ok": False, "error": "No file or URL provided"}, status_code=400)
    try:
        if file:
            content = (await file.read()).decode("utf-8")
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers={"User-Agent": USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if not resp.ok:
                        return JSONResponse(
                            {"ok": False, "error": f"HTTP {resp.status}"}, status_code=400)
                    content = await resp.text()
        result = await asyncio.get_running_loop().run_in_executor(None, _parse_opml, content)
        if result.bozo:
            raise ValueError(str(result.bozo_exception))
        feeds = [{"url": f.url, "title": f.title or f.url} for f in result.feeds if f.url]
        opml_title = getattr(result.meta, "title", "") or ""
        return {"ok": True, "title": opml_title, "feeds": feeds}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/fetch_feed")
async def fetch_feed(request: Request, url: Optional[str] = None):
    token       = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    kvstore_url = request.headers.get("X-Kvstore-Url", "").strip()

    if not kvstore_url or not await _verify_token(token, kvstore_url):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)

    try:
        result = await _fetch_and_cache(url)
        response = {"ok": True, "title": result["title"], "feed_url": url, "items": result["items"]}
        if result.get("author_did"):
            response["author_did"] = result["author_did"]
        if result.get("stale"):
            response["stale"] = True
            response["error"] = result.get("error", "")
        return response
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/feed_meta")
async def feed_meta(url: Optional[str] = None):
    """Return feed title and author_did without items. Public — no auth required."""
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    try:
        result = await _fetch_and_cache(url)
        return {"ok": True, "title": result["title"], "author_did": result.get("author_did")}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
