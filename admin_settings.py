# Redis-backed variant of the generic admin-settings module (see
# /srv/shared/admin_settings_redis.py for the reference copy — never mounted
# or imported at runtime). Each adopting app keeps its own verbatim copy.
# When you change this file, copy the change into every adopting app's
# copy by hand.
#
# Differences from the other variants:
#   - /srv/shared/admin_settings.py       — Flask + sqlite3 (sync, cached g.db)
#   - /srv/shared/admin_settings_fastapi.py — FastAPI + aiosqlite (async, Depends())
#   - this file                            — FastAPI + Redis (async, manual header
#     parsing — this app has no Depends()/Header() usage anywhere, so the new
#     routes follow its existing idiom instead of introducing one)
# Settings live in a single Redis hash (HSET admin_settings <key> <value>),
# not a table — there is no separate init step, HSET creates the hash on
# first write. `get_redis` is a zero-arg callable returning the app's current
# redis client, not the client object itself — the real client is only
# assigned inside the app's lifespan() at startup, after routes are already
# registered at import time, so routes must look it up fresh on every call.
#
# Contract:
#   SettingField(key, label, type, sensitive, validate, help)
#     - type in {"text", "url", "secret", "boolean"}
#     - "boolean" values are stored/transmitted as the literal strings
#       "true"/"false" (same hash value as everything else) — the CList
#       renderer draws a checkbox for this type and the app treats the
#       string "false" as off, anything else as on.
#     - validate: optional str -> str|None (error message, or None if valid)
#   await get_setting(get_redis, key, default=None)   — call at point of use, every call
#   is_admin(username)                                 — username in ADMIN_USERNAMES
#   register_admin_settings_routes(app, schema, get_redis, require_admin, defaults=None)
#     — registers GET/PUT /admin/settings. `require_admin` is an async
#     callable `require_admin(request) -> (username|None, (body, status)|None)`,
#     matching this app's existing manual-header-parsing style.
#
# Adopting an app:
#   1. Copy this file into the app directory verbatim.
#   2. Declare SETTINGS_SCHEMA and an async require_admin(request) helper.
#   3. Call register_admin_settings_routes(app, SETTINGS_SCHEMA, get_redis, require_admin, defaults).
#   4. Replace frozen constant reads at their point of use with
#      await get_setting(get_redis, "KEY", default=os.environ.get("KEY", "...")).
#   5. Add ADMIN_USERNAMES=<comma-separated usernames> to .env / compose environment.
#   6. Update that app's CLAUDE.md: new env var, new /admin/settings
#      endpoints, Redis-override-falls-back-to-env precedence.

import os
from collections import namedtuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SETTINGS_HASH_KEY = "admin_settings"

SettingField = namedtuple("SettingField", ["key", "label", "type", "sensitive", "validate", "help"])
SettingField.__new__.__defaults__ = (None, None)  # validate, help are optional

ADMIN_USERNAMES = {
    u.strip() for u in os.environ.get("ADMIN_USERNAMES", "").split(",") if u.strip()
}


def is_admin(username):
    return bool(username) and username in ADMIN_USERNAMES


async def get_setting(get_redis, key, default=None):
    value = await get_redis().hget(SETTINGS_HASH_KEY, key)
    return value if value else default


async def _set_settings(get_redis, data: dict):
    await get_redis().hset(SETTINGS_HASH_KEY, mapping=data)


def _mask(value):
    # Fixed-length mask regardless of real length, so the mask itself never
    # leaks how long the underlying secret is.
    if not value:
        return None
    return "•" * 8 + value[-4:]


def register_admin_settings_routes(app: FastAPI, schema, get_redis, require_admin, defaults=None):
    """Registers GET/PUT /admin/settings on `app`. `schema` is a list of
    SettingField. `get_redis` is a zero-arg callable returning the app's
    current Redis client. `require_admin` is an async callable
    `require_admin(request) -> (username|None, (body, status)|None)`,
    matching this app's existing manual-header-parsing auth style. `defaults`
    is an optional {key: value} map of the env-sourced fallback each field
    would resolve to if no admin override exists yet — the same value the
    app's own point-of-use get_setting(..., default=...) call uses. Without
    it, GET would show every unsaved field as empty even though the app is
    actually running on a real value from the environment."""
    schema_by_key = {f.key: f for f in schema}
    defaults = defaults or {}

    def _schema_json():
        return [
            {"key": f.key, "label": f.label, "type": f.type, "sensitive": f.sensitive, "help": f.help}
            for f in schema
        ]

    async def _masked_values():
        out = {}
        for f in schema:
            raw = await get_setting(get_redis, f.key, default=defaults.get(f.key))
            out[f.key] = _mask(raw) if f.sensitive else raw
        return out

    @app.get("/admin/settings")
    async def admin_get_settings(request: Request):
        username, err = await require_admin(request)
        if err:
            return JSONResponse(err[0], status_code=err[1])
        return {"schema": _schema_json(), "values": await _masked_values()}

    @app.put("/admin/settings")
    async def admin_put_settings(request: Request):
        username, err = await require_admin(request)
        if err:
            return JSONResponse(err[0], status_code=err[1])

        data = await request.json()
        for key in data:
            if key not in schema_by_key:
                return JSONResponse({"error": f"Unknown setting: {key}"}, status_code=400)
        for key, value in data.items():
            validate = schema_by_key[key].validate
            if validate:
                error = validate(value)
                if error:
                    return JSONResponse({"error": f"{key}: {error}"}, status_code=400)

        # Validate-then-write: nothing is persisted unless every key in the
        # request passes, so a partial PUT never leaves settings half-applied.
        await _set_settings(get_redis, data)
        return {"schema": _schema_json(), "values": await _masked_values()}
