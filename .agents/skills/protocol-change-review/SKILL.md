---
name: protocol-change-review
description: Run the three required checks (compliance, latest specification, safety) on a gunicorn change, commit or pull request that touches HTTP/1, HTTP/2, h2c, WebSocket, ASGI/WSGI framing, uWSGI, PROXY protocol, TLS/ALPN, keep-alive, limits or connection state. Use before committing, before opening or merging a PR, when reviewing a contributor PR, and when asked whether code follows a spec.
---

# Protocol change review

Gunicorn talks to untrusted clients, often behind a proxy. A change is done
when it matches the spec, the spec is the current one, and a hostile peer
cannot use it. Run the three checks below on each commit; a PR with several
commits gets one verdict per commit. The spec list is in
[AGENTS.md](../../../AGENTS.md#specifications).

## 1. Compliance

Get the spec text. Never quote it from memory.

```bash
mkdir -p "$TMPDIR/rfc" && cd "$TMPDIR/rfc"
for r in 9110 9112 9113 9931 7541 6455 8297 3986; do
  [ -f rfc$r.txt ] || curl -sfL https://www.rfc-editor.org/rfc/rfc$r.txt -o rfc$r.txt
done
grep -n "MUST be rejected" rfc9112.txt
```

For each commit:

1. Find every spec sentence the commit, PR or code comment cites. Confirm it
   is verbatim and in the section named.
2. Read the whole section: exceptions, "unless", and the rule for the other
   role (client/server, sender/recipient, proxy/origin) are usually a
   paragraph away.
3. Note the level. MUST / MUST NOT is a fix. SHOULD needs a reason to skip.
   MAY is a choice the change has to justify. Rejecting what the spec allows
   breaks clients.
4. Check the response matches the text: 400 vs 414 vs 431 vs 501, close vs
   keep-alive, RST_STREAM vs GOAWAY and the error code.
5. Check every path that reaches the code:
   - HTTP/1: WSGI parser (`http/message.py`, `http/body.py`), ASGI
     `PythonProtocol` (`asgi/parser.py`), gunicorn_h1c. All three must accept
     and reject the same bytes; probe them side by side.
   - Workers: sync, gthread, gevent, tornado, asgi.
   - HTTP/2 over TLS and h2c (prior knowledge and `Upgrade: h2c`).
   - Behind `proxy_protocol`, `protocol = uwsgi`, and with keep-alive and
     pipelining.
6. Check the test fails on master and passes with the change. Use a worktree
   at the merge base, not `git stash`, and put it first on `PYTHONPATH` so the
   editable install does not shadow it:

```bash
git worktree add "$TMPDIR/base" origin/master
cp tests/test_x.py "$TMPDIR/base/tests/"
cd "$TMPDIR/base" && PYTHONPATH="$PWD" ../path/to/.venv/bin/python -m pytest tests/test_x.py
```

Suites to run (see AGENTS.md for commands): the unit suite, the HTTP/1 request
corpus (`tests/requests/{valid,invalid}`), `h2spec` for HTTP/2,
`asgi_compliance`, `http2`, `uwsgi` and the k6 stress smoke for connection
handling.

## 2. Latest specification

1. Name the governing document and confirm it is current on
   https://datatracker.ietf.org/doc/rfcNNNN/ ("Obsoleted by", "Updated by").
   Known replacements: RFC 7230/7231/2616 to RFC 9110/9112, RFC 7540 to
   RFC 9113; RFC 9931 updates RFC 9112 for Upgrade and CONNECT.
2. For ASGI, check https://asgi.readthedocs.io/ for the spec version the
   scope advertises. For WSGI, PEP 3333.
3. Check for errata on https://www.rfc-editor.org/errata/rfcNNNN and for an
   active draft that changes the rule (httpbis working group).
4. Write the version and the date checked in the PR description.
5. If the latest text disagrees with the code, fix it in the change or say in
   the PR that it is out of scope.

## 3. Safety

Walk the classes that apply and state which you checked.

- **Request smuggling**: any disagreement on message length between gunicorn
  and a front proxy. Content-Length vs Transfer-Encoding, duplicate or
  malformed Content-Length, non SP/HTAB whitespace, header name whitespace,
  bare LF / CR, chunk-size and chunk terminator parsing, obs-fold, request
  bodies left unread on keep-alive, HTTP/1.0 keep-alive, Upgrade bytes read as
  HTTP/1, bytes after a CONNECT served as a request (RFC 9931).
- **Response splitting / desync**: unchecked header names or values written
  by the app, body bytes beyond Content-Length, a response that ends early on
  a kept-alive connection, a response written to the wrong request when
  pipelining.
- **Resource exhaustion**: every per-connection buffer, header count and size,
  line length, chunk-extension and trailer size, idle and keep-alive timeouts,
  concurrent streams, pending writes. A peer must not grow any of them without
  a bound set by `limit_request_*`, `keepalive`, `timeout` or an HTTP/2 setting.
- **HTTP/2 floods**: Rapid Reset (CVE-2023-44487), MadeYouReset
  (CVE-2025-8671), CONTINUATION flood (CVE-2024-27316), HPACK bomb,
  SETTINGS / PING / empty DATA floods, flow-control stalls and window
  overflow. Tear down with `GOAWAY(ENHANCE_YOUR_CALM)` past a cap.
- **WebSocket**: unmasked client frames, oversized frames and messages,
  fragmented control frames, close handshake.
- **Trust boundaries**: `forwarded_allow_ips`, `proxy_allow_ips`,
  `X-Forwarded-*` and PROXY headers honoured only from trusted peers.

Never weaken a limit to let a legitimate client pass; exclude that case
precisely. A regression test for an attack drives it over a raw socket or
through the parser and asserts the bound or the rejection.

A finding from this check is a bug when its fix is to follow the spec, even
if it is a smuggling, splitting or exhaustion vector: public PR, changelog
under Bug Fixes with the spec section, no advisory, no CVE, no attack
description. See "Specification issues are bugs, not security issues" in
AGENTS.md for the rule and the few cases that do go through SECURITY.md.

## Report

One block per commit, in the PR description or the hand-off:

```
<sha> <subject>
  spec: RFC 9112 §7.1 MUST, quote verified | not found | paraphrased
  latest: RFC 9112 current (checked 2026-11-07), updated by RFC 9931 (n/a)
  verdict: compliant | partial (<missing>) | wrong (<why>) | not a spec item
  parsers: WSGI / ASGI / h1c agree | differ (<how>)
  test: fails before, passes after | does not discriminate | missing
  safety: <classes checked>, <bounds>, no new unbounded state
```

Then list what needs the maintainer's decision: a SHOULD left out, a
deliberate deviation, a spec update that is out of scope.
