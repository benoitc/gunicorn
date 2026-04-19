# ASGI Framework Compatibility Grid

**Generated:** 2026-04-04 03:00:27
**Worker:** gunicorn ASGI worker (`-k asgi`)
**Event Loop:** auto (uvloop if available)

## Summary

| Framework | HTTP Scope | HTTP Messages | WebSocket | Lifespan | Streaming | Total |
|-----------|---------|---------|---------|---------|---------|-------|
| Django + Channels | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| FastAPI | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| Starlette | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| Quart | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| Litestar | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| BlackSheep | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |

*Bold indicates failures*

**Overall:** 438/444 tests passed (98%)
