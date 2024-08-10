# Security Policy

## Reporting a Vulnerability

**Please note that public Github issues are open for everyone to see!**

If you believe you are found a problem in Gunicorn software, examples or documentation, we encourage you to send your
 report privately via [email](mailto:security@gunicorn.org?subject=Security%20issue%20in%20Gunicorn), or via Github
 using the *Report a vulnerability* button in the [Security](https://github.com/benoitc/gunicorn/security) section.

## Supported Releases

At this time, **only the latest release** receives any security attention whatsoever.

Please target reports against :white_check_mark: or current master. Please understand that :x: will
 not receive further security attention.

| Version | Status          |
| ------- | ------------------ |
| 23.0.0  | :white_check_mark: |
| 22.0.0  | :x: |
| 21.2.0  | :x: |
| 20.0.0  | :x: |
| < 20.0  | :x: |

## Python Versions

Gunicorn runs on Python 3.7+, we *highly recommend* the latest release of a 
[supported series](https://devguide.python.org/versions/) and will not prioritize issues exclusively 
affecting in EoL environments.
