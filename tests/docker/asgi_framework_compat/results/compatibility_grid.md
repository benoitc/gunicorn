# ASGI Framework Compatibility Grid

**Generated:** 2026-04-03 21:49:07
**Worker:** gunicorn ASGI worker (`-k asgi`)
**Event Loop:** auto (uvloop if available)

## Summary

| Framework | HTTP Scope | HTTP Messages | WebSocket | Lifespan | Streaming | Total |
|-----------|---------|---------|---------|---------|---------|-------|
| Django + Channels | 19/19 | **18/19** | 19/19 | **7/8** | 9/9 | **72/74** |
| FastAPI | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| Starlette | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |
| Quart | **18/19** | **17/19** | **11/19** | 8/8 | 9/9 | **63/74** |
| Litestar | **18/19** | **11/19** | **17/19** | 8/8 | 9/9 | **63/74** |
| BlackSheep | 19/19 | **18/19** | 19/19 | 8/8 | 9/9 | **73/74** |

*Bold indicates failures*

**Overall:** 417/444 tests passed (93%)
