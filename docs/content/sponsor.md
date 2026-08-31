# Support Gunicorn

Gunicorn has been serving Python web applications since 2010. It's downloaded
millions of times per month and runs in production at companies of all sizes.

No company pays for gunicorn's maintenance. The work happens in unpaid time, and
that is what sets how fast it moves. Sponsorship changes that directly: it buys
days that would otherwise go to client work.

## What your sponsorship funds

Where the time goes, in priority order:

- **Release stabilization**: working through the open reports and pull requests,
  reviewing contributions and getting the fixes people are waiting on into a
  release. This is the bulk of it, and it is the part that goes undone when
  there is no time
- **Security**: responding to reported vulnerabilities
- **HTTP/2**: h2c support across the HTTP/2-capable workers, and hardening what
  shipped as beta
- **ASGI**: tracking the spec as FastAPI, Starlette and Quart move
- **Python compatibility**: keeping up with new Python releases
- **Documentation**: keeping the guides and the settings reference current

Two larger pieces of new work, neither started:

- **Serving AI workloads**: dirty arbiters already give a model its own process
  pool, with per-app worker allocation and streaming responses. The work ahead
  is what a model server needs on top of that: batching requests so a single
  forward pass serves many of them, backpressure when the queue outgrows the
  workers, and pinning workers to specific GPUs
- **HTTP/3**: QUIC support, alongside finishing HTTP/2. The protocol is already
  reserved in the configuration and does nothing yet

This is what gets worked on, in the order it gets worked on. It is not a
schedule, and nothing here carries a date.

Sustained sponsorship funds full-time months rather than evenings. When it does,
what it paid for goes in the [release notes](news.md), so you can see what your
money bought.

## How to support

### Donate

<p>
  <a href="https://github.com/sponsors/benoitc"><img src="https://img.shields.io/badge/GitHub_Sponsors-❤-ea4aaa?style=for-the-badge&logo=github" alt="GitHub Sponsors"></a>
  <a href="https://checkout.revolut.com/pay/74cf6fe1-358e-4880-b800-3f0936ce94be"><img src="https://img.shields.io/badge/Revolut-Donate-191c20?style=for-the-badge" alt="Revolut"></a>
</p>

- **[GitHub Sponsors](https://github.com/sponsors/benoitc)**: monthly or one-time
- **[Revolut](https://checkout.revolut.com/pay/74cf6fe1-358e-4880-b800-3f0936ce94be)**: direct donations, individuals and companies

### Corporate sponsorship

If gunicorn is part of your infrastructure:

- **Recurring sponsorship** through [GitHub Sponsors](https://github.com/sponsors/benoitc)
- **Sponsored support contracts** for priority bug fixes and feature requests
- **Logo placement** on this site and in the README

## Sponsors

<a href="https://enki-multimedia.eu" target="_blank" rel="noopener">
  <img src="../assets/enki-multimedia.svg" alt="Enki Multimedia" style="height: 50px;" />
</a>
