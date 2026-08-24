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

Larger pieces of work that are planned, or begun but not landed.

**Serving AI workloads** (resource-aware, lifecycle-aware workers). Dirty
arbiters already give heavy applications such as ML models their own process
pools, with per-app worker allocation and streaming responses. The next step is
to make those workers resource-aware and lifecycle-aware without turning
Gunicorn into an inference engine.

Applications will be able to request operator-defined resource slots, initially
targeting GPU-backed workloads, while Gunicorn manages allocation, readiness,
backpressure and graceful worker replacement. Resource slots are virtual
allocation tokens: the application and its inference engine remain responsible
for the physical device, model memory, batching and parallelism.

The goal is for Gunicorn to complement engines such as vLLM, SGLang, llama.cpp
or PyTorch by managing their application lifecycle cleanly, rather than
replacing them.

**HTTP/3.** QUIC support, alongside finishing HTTP/2. The protocol is already
reserved in the configuration and does nothing yet.

**FastCGI.** A FastCGI responder alongside the existing
[uWSGI protocol](uwsgi.md) support, so gunicorn can sit behind nginx or Apache
over FCGI instead of HTTP proxying. A working branch exists in
[#3466](https://github.com/benoitc/gunicorn/pull/3466); it needs finishing and
review.

None of these are settled. If you have a use case, a design opinion or a
constraint any of them would break, say so in
[Ideas](https://github.com/benoitc/gunicorn/discussions/categories/ideas) —
that is what shapes the order and the shape of the work.

## Not planned

**Windows support.** Gunicorn is a pre-fork UNIX server. The process model is
the product, and it does not port.

## Influencing this

The ordering is not fixed. Things that move it:

- A clear bug report with a reproduction moves the fix up.
- A pull request with tests moves the feature up further.
- [Sponsorship](sponsor.md) converts evenings into days, which is what
  determines how much of the "Next" section happens at all.

If something important to you is missing here, open an
[Idea](https://github.com/benoitc/gunicorn/discussions/categories/ideas), or
come [ask in chat](https://web.libera.chat/?channels=%23gunicorn).
