# Agents

Instructions for AI coding agents working on gunicorn. Read this file before
you change anything; it applies to every agent and every change.

## Project

Gunicorn is a pre-fork HTTP server for Python: WSGI (sync, gthread, gevent,
tornado workers) and ASGI (asgi worker), with HTTP/1.1, HTTP/2 (TLS and h2c),
WebSocket, the uWSGI binary protocol and the PROXY protocol. Python 3.10+.
Pure Python; optional extras are `h2` (HTTP/2) and `gunicorn_h1c` (fast HTTP/1
parser).

## First principle: compliance, latest spec, safety

Gunicorn faces untrusted clients. Every change that touches how bytes are read,
parsed, framed or written, or how a connection or stream changes state, must
pass three checks before it is called done, committed or opened as a pull
request:

1. **Compliance**: the behaviour matches the governing spec section, and a test
   shows the accept and the reject path. The test fails on master without the
   change.
2. **Latest specification**: you checked that the spec you cite is the current
   one (not obsoleted, no newer draft that changes the rule), and you read the
   section itself instead of quoting from memory.
3. **Safety**: the change does not open a known abuse class (request smuggling,
   response splitting, resource exhaustion, flood) and every per-peer resource
   it touches stays bounded.

Use the [protocol-change-review](.agents/skills/protocol-change-review/SKILL.md)
skill to run them. When in doubt whether a change is protocol code, it is.

## Specification issues are bugs, not security issues

A report is a specification issue when the fix is to make gunicorn do what a
spec it implements says (see [Specifications](#specifications)):

- input accepted, rejected or framed differently from the spec (request
  line, fields, Content-Length, Transfer-Encoding, chunked coding, trailers,
  HTTP/2 frames, WebSocket frames, uWSGI or PROXY headers);
- gunicorn's parsers (WSGI, ASGI, gunicorn_h1c, HTTP/2) disagreeing with
  each other on the same bytes;
- application output written without the checks the spec requires (status
  line, header names and values, body length vs Content-Length);
- a missing or wrong bound that the spec or a setting defines (line and
  field limits, timeouts, keep-alive, flow-control windows, frame sizes).

This holds even when the report calls it request smuggling, response
splitting, desync or denial of service. Treat it as a bug:

- fix it in a public pull request, with a public issue if one is needed;
- list it under **Bug Fixes** in the changelog, one plain line citing the
  spec section;
- do not open a GitHub Security Advisory, request a CVE, embargo the fix,
  give it a severity, or describe how to attack it;
- when it arrived as an advisory, close the advisory as not a vulnerability
  and link the pull request that fixes it.

Only a problem that is not a spec deviation goes through
[SECURITY.md](SECURITY.md): code execution, file access outside what the
configuration allows, privilege or permission handling (user, group, umask,
socket and pid file modes), one client's request data reaching another
client, or gunicorn weakening TLS. A spec deviation stays a bug even when its
effect is on this list: per-request state shared across requests because the
ASGI lifespan copy was skipped is a bug. If unsure, ask the maintainer before
treating anything as a security issue.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[testing]" -r requirements_test.txt
```

Always run tests from the venv: subprocess-based tests fail otherwise.

## Required checks

These match what CI gates on.

```bash
.venv/bin/pytest                                   # full suite
.venv/bin/pytest tests/test_http.py -k chunked     # one file / one test
.venv/bin/pycodestyle gunicorn                     # style (tox -e pycodestyle)
tox -e lint                                        # pylint, max line 120
# CI runs pylint 3.3.2 under Python 3.12, which reports things 3.13 does not:
uv run --no-project --python 3.12 --with pylint==3.3.2 -- pylint -j0 --max-line-length=120 gunicorn
mkdocs build --strict                              # docs, regenerates settings.md
```

Protocol suites (need Docker, see `tests/docker/README.md`; never run
`pytest tests/docker` in one go):

```bash
PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh h2spec
PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh asgi_compliance http2 uwsgi
.venv/bin/pytest tests/docker/stress/test_stress.py          # k6 smoke
```

HTTP/1 request corpus: `tests/requests/valid` and `tests/requests/invalid`,
run by `tests/test_valid_requests.py` and `tests/test_invalid_requests.py` with
both the Python parser and gunicorn_h1c.

## Layout

- `gunicorn/arbiter.py`: master process, worker lifecycle, signals.
- `gunicorn/workers/`: sync, gthread, gevent, tornado, asgi (`gasgi.py`).
- `gunicorn/http/`: WSGI HTTP/1 parser (`message.py`, `body.py`, `unreader.py`) and response (`wsgi.py`).
- `gunicorn/asgi/`: ASGI protocol, pure-Python HTTP/1 parser (`parser.py`), WebSocket, lifespan.
- `gunicorn/http2/`: HTTP/2 on top of `h2`, ALPN and h2c negotiation.
- `gunicorn/uwsgi/`, `gunicorn/asgi/uwsgi.py`: uWSGI protocol.
- `gunicorn/config.py`: every setting; `docs/content/reference/settings.md` is generated from it.

## Conventions

- Style: PEP 8 via pycodestyle, pylint at 120 columns. Standard library only
  in the core; new dependencies go behind an extra.
- Every bug fix and feature has a test. Show it failing on master.
- The three HTTP/1 parsers (WSGI `http/message.py`, ASGI `asgi/parser.py`,
  gunicorn_h1c) must accept and reject the same input. A fix in one is checked
  in the others.
- Never relax a limit or a rejection to make a client pass; exclude the
  legitimate case precisely.
- New settings go in `gunicorn/config.py`, then `mkdocs build`.
- Changelog: one plain line per fix in `docs/content/2026-news.md` and
  `docs/content/news.md` (same section), citing the spec section when there is
  one. No implementation details, no attack narratives.
- Contributors add themselves to `THANKS`, sorted.
- Don't commit the regenerated `tests/docker/**/certs/server.{crt,key}`.
- `tests/test_asgi_worker.py::TestASGIIntegration::test_http_request_response`
  is flaky under the full suite; rerun it alone before blaming a change.

## Pull requests and commits

- One topic per pull request; related fixes are grouped, each in its own
  commit with its tests and docs.
- Descriptions state what was wrong, the fix in a few lines, and breaking
  changes. Reference issues with `Fixes #N`. No test plan, no file-by-file
  walkthrough.
- No `Co-Authored-By`, "Generated with" or similar trailers.
- Follow "Write for the person who reads it" in
  [CONTRIBUTING.md](CONTRIBUTING.md#write-for-the-person-who-reads-it): plain
  English, no inflated or pseudo-technical wording, and a person has read the
  change before it is opened.

## Specifications

The specs gunicorn implements. Cite the current one in code and changelog.
Last checked: 2026-11-07.

### HTTP

| Spec | Scope in gunicorn | Code |
|---|---|---|
| RFC 9110 HTTP Semantics | methods, status codes, fields, Content-Length, Expect, trailers | `http/`, `asgi/`, `http2/` |
| RFC 9112 HTTP/1.1 | request line, field parsing, line endings (§2.2), Transfer-Encoding framing (§6.1, §6.3), chunked coding and extensions (§7.1), keep-alive, 414 | `http/message.py`, `http/body.py`, `asgi/parser.py` |
| RFC 9931 Optimistic protocol transitions (updates RFC 9112) | a CONNECT always ends the connection (§8); a rejected `Upgrade` keeps HTTP/1.1 (§5) | `http/message.py`, `asgi/parser.py` |
| RFC 9113 HTTP/2 | frames, streams, flow control, SETTINGS, GOAWAY, prior-knowledge h2c (§3.3) | `http2/` |
| RFC 7540 §3.2 HTTP/2 Upgrade (obsoleted by RFC 9113) | `Upgrade: h2c` from HTTP/1.1, kept for compatibility; RFC 9113 deprecates it | `http2/negotiation.py` |
| RFC 7541 HPACK | header compression (through `h2`) | `h2` |
| RFC 7540 §5.3 stream priority (deprecated by RFC 9113 §5.3.1) | PRIORITY frames tracked per stream; RFC 9218 PRIORITY_UPDATE is not implemented | `http2/async_connection.py` |
| RFC 8297 103 Early Hints | WSGI `early_hints`, ASGI `http.response.informational` | `http/wsgi.py`, `asgi/protocol.py`, `http2/` |
| RFC 7301 TLS ALPN | `h2` / `http/1.1` negotiation | `sock.py`, `http2/negotiation.py` |
| RFC 8446 TLS 1.3 | TLS through the `ssl` module | `sock.py` |
| RFC 3986 URI | request-target forms, percent-encoding | `http/message.py`, `asgi/parser.py` |
| RFC 6455 WebSocket | handshake, framing, close handshake, masking | `asgi/websocket.py` |

`X-Forwarded-*` headers are de facto, not specified; the RFC 7239 `Forwarded`
header is not parsed. RFC 8441 (WebSocket over HTTP/2) is not implemented.
RFC 7230, 7231, 2616 and 7540 still appear in comments: they are obsoleted by
RFC 9110, 9112 and 9113; use the new numbers in new code.

### Application interfaces

| Spec | Scope |
|---|---|
| PEP 3333 WSGI 1.0.1 (and RFC 3875 CGI for environ variables) | WSGI environ, `start_response`, `wsgi.input`, file wrapper |
| ASGI 3.0, HTTP and WebSocket spec 2.4 | `scope`, `receive`/`send` events, `http.response.trailers` extension |
| ASGI lifespan spec | `lifespan.startup` / `shutdown` events, failure handling |

### Proxy and process protocols

| Spec | Scope |
|---|---|
| HAProxy PROXY protocol v1 and v2 | `proxy_protocol` setting |
| uWSGI binary protocol (uWSGI docs, packet modifier 0) | `protocol = uwsgi` |
| systemd socket activation (`sd_listen_fds`) and `sd_notify` | `systemd.py` |
| StatsD / DogStatsD line protocol | `instrument/statsd.py` |

## Skills

Task guides live in `.agents/skills/<name>/SKILL.md`; read the one that
matches the task before starting. `.claude/skills` links to the same
directory, so there is one copy.

- [protocol-change-review](.agents/skills/protocol-change-review/SKILL.md):
  the three checks above (compliance, latest spec, safety) for a change, a
  commit or a pull request.
