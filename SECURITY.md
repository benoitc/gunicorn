# Security Policy

## Reporting a Vulnerability

**Please note that public Github issues are open for everyone to see!**

If you found a security issue in Gunicorn, send your report privately via
[email](mailto:security@gunicorn.org?subject=Security%20issue%20in%20Gunicorn), or via GitHub using the
*Report a vulnerability* button in the [Security](https://github.com/benoitc/gunicorn/security) section.

## What is a security issue

Private reports are for problems that are not a deviation from a
specification gunicorn implements: code execution, file access beyond what
the configuration allows, user, group and permission handling, one client's
data reaching another client outside any specification rule, or gunicorn
weakening TLS.

## What is a bug

When the fix is to make gunicorn follow a specification it implements
(HTTP/1.1, HTTP/2, WebSocket, WSGI, ASGI, uWSGI, PROXY protocol), it is a
bug, even when described as request smuggling, response splitting, desync or
denial of service. Report it as a public bug and cite the specification
section; see [Security issues and specification bugs](CONTRIBUTING.md#security-issues-and-specification-bugs).
We don't publish advisories or request CVEs for these, and advisories filed
for them are closed as bugs with a link to the fix.

Write the report in plain English, with a minimal reproduction, as described
in [CONTRIBUTING.md](CONTRIBUTING.md#write-for-the-person-who-reads-it).

## Supported Releases

Please target reports against :white_check_mark: or current master. Please understand that :x: will
 not receive further security attention.

| Version | Status             |
| ------- | ------------------ |
| 26.0.0  | :white_check_mark: |
| 25.3.0  | :white_check_mark: |
| 24.1.1  | :x:                |
| 23.0.0  | :x:                |
| 22.0.0  | :x:                |
| < 22.0  | :x:                |

## Python Versions

Gunicorn runs on Python 3.10+, supporting Python versions that are still maintained by the PSF.
We *highly recommend* the latest release of a [supported series](https://devguide.python.org/versions/)
and will not prioritize issues affecting EoL environments.
