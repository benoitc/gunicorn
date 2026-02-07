# Gunicorn

<p align="center">
  <strong>Gunicorn is maintained by volunteers. If it powers your production, please consider supporting us:</strong><br>
  <a href="https://github.com/sponsors/benoitc"><img src="https://img.shields.io/badge/GitHub_Sponsors-❤-ea4aaa?style=for-the-badge&logo=github" alt="GitHub Sponsors"></a>
  <a href="https://opencollective.com/gunicorn"><img src="https://img.shields.io/badge/Open_Collective-Support-7FADF2?style=for-the-badge&logo=opencollective" alt="Open Collective"></a>
  <a href="https://checkout.revolut.com/pay/c934e028-3a71-44eb-b99c-491342df2044"><img src="https://img.shields.io/badge/Revolut-Donate-191c20?style=for-the-badge" alt="Revolut"></a>
</p>

[![PyPI version](https://img.shields.io/pypi/v/gunicorn.svg?style=flat)](https://pypi.python.org/pypi/gunicorn)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/gunicorn.svg)](https://pypi.python.org/pypi/gunicorn)
[![Build Status](https://github.com/benoitc/gunicorn/actions/workflows/tox.yml/badge.svg)](https://github.com/benoitc/gunicorn/actions/workflows/tox.yml)

Gunicorn 'Green Unicorn' is a Python WSGI HTTP Server for UNIX. It's a pre-fork
worker model ported from Ruby's [Unicorn](https://bogomips.org/unicorn/) project. The Gunicorn server is broadly
compatible with various web frameworks, simply implemented, light on server
resource usage, and fairly speedy.

**New in v25**: Per-app worker allocation for dirty arbiters, HTTP/2 support (beta)!

## Quick Start

```bash
pip install gunicorn
gunicorn myapp:app --workers 4
```

For ASGI applications (FastAPI, Starlette):

```bash
gunicorn myapp:app --worker-class asgi
```

## Features

- WSGI support for Django, Flask, Pyramid, and any WSGI framework
- **ASGI support** (beta) for FastAPI, Starlette, Quart
- **HTTP/2 support** (beta) with multiplexed streams
- **Dirty Arbiters** for heavy workloads (ML models, long-running tasks)
- uWSGI binary protocol for nginx integration
- Multiple worker types: sync, gthread, gevent, eventlet, asgi
- Graceful worker process management
- Compatible with Python 3.9+

## Documentation

Full documentation at https://gunicorn.org

- [Quickstart](https://gunicorn.org/quickstart/)
- [Configuration](https://gunicorn.org/configure/)
- [Deployment](https://gunicorn.org/deploy/)
- [Settings Reference](https://gunicorn.org/reference/settings/)

## Community

- Report bugs on [GitHub Issues](https://github.com/benoitc/gunicorn/issues)
- Chat in [#gunicorn](https://web.libera.chat/?channels=#gunicorn) on [Libera.chat](https://libera.chat/)
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines

## Support

gunicorn has been serving Python web applications since 2010. If it's running in your production stack and saving your team time and money, please consider supporting its continued development:

[![Sponsor](https://img.shields.io/badge/sponsor-❤-ff69b4)](https://github.com/sponsors/benoitc)

Your sponsorship helps cover:
- Security updates and vulnerability responses
- Compatibility with new Python versions
- Bug fixes and performance improvements
- Documentation maintenance

**Corporate sponsors:** If gunicorn is part of your infrastructure, [reach out](mailto:benoitc@enki-multimedia.eu) for sponsored support options.

## License

Gunicorn is released under the MIT License. See the [LICENSE](https://github.com/benoitc/gunicorn/blob/master/LICENSE) file for details.
