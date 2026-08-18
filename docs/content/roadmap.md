# Roadmap

Where gunicorn is going, and what is being worked on now. This is priority
order, not a schedule: nothing here carries a date, and items move when
circumstances or funding change.

Gunicorn is maintained in unpaid time. That is the constraint behind every
ordering decision on this page. See [Support Gunicorn](sponsor.md) for how that
changes.

## Now

The current focus, roughly in order.

**Release stabilization.** Working through open reports and pull requests,
reviewing contributions, and getting fixes into releases. This is the bulk of
the work and the part that goes undone when there is no time.

**Security.** Responding to reported vulnerabilities, and keeping the HTTP
parsers aligned with RFC 9110 and RFC 9112 on request framing, header syntax
and smuggling defenses.

**HTTP/2.** Taking what shipped as beta toward something dependable, including
`h2c` support across the HTTP/2-capable workers.

**ASGI.** Tracking the spec as FastAPI, Starlette, Quart and the rest move,
with the compatibility suite as the check on that.

**Python compatibility.** Keeping up with new Python releases.

**Documentation.** Keeping the guides and the settings reference current.

## Next

Larger pieces of work that are planned but not started.

**Serving AI workloads.** Dirty arbiters already give a model its own process
pool, with per-app worker allocation and streaming responses. The work ahead is
what a model server needs on top of that: batching requests so a single forward
pass serves many of them, backpressure when the queue outgrows the workers, and
pinning workers to specific GPUs.

**HTTP/3.** QUIC support, alongside finishing HTTP/2. The protocol is already
reserved in the configuration and does nothing yet.

## Not planned

Saying no is part of a direction.

- **Windows support.** Gunicorn is a pre-fork UNIX server. The process model is
  the product, and it does not port.
- **Becoming an application framework.** Gunicorn runs your app; it does not
  want to be your router, your ORM or your task queue.
- **Replacing a reverse proxy.** Run gunicorn behind nginx or similar. TLS
  termination, static files and request buffering belong there.

## Influencing this

The ordering is not fixed. Things that move it:

- A clear bug report with a reproduction moves the fix up.
- A pull request with tests moves the feature up further.
- [Sponsorship](sponsor.md) converts evenings into days, which is what
  determines how much of the "Next" section happens at all.

Open a [discussion](https://github.com/benoitc/gunicorn/discussions) if
something important to you is missing here, or come
[ask in chat](https://web.libera.chat/?channels=%23gunicorn).
