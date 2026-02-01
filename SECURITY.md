# Security Policy

## Reporting a Vulnerability

**Please note that public Github issues are open for everyone to see!**

If you believe you are found a problem in Gunicorn software, examples or documentation, we encourage you to send your
 report privately via [email](mailto:security@gunicorn.org?subject=Security%20issue%20in%20Gunicorn), or via Github
 using the *Report a vulnerability* button in the [Security](https://github.com/benoitc/gunicorn/security) section.

## Supported Releases

Please target reports against :white_check_mark: or current master. Please understand that :x: will
 not receive further security attention.

| Version | Status             |
| ------- | ------------------ |
| 25.0.0  | :white_check_mark: |
| 24.1.1  | :white_check_mark: |
| 23.0.0  | :x:                |
| 22.0.0  | :x:                |
| < 22.0  | :x:                |

## Python Versions

Gunicorn runs on Python 3.10+, supporting Python versions that are still maintained by the PSF.
We *highly recommend* the latest release of a [supported series](https://devguide.python.org/versions/)
and will not prioritize issues affecting EoL environments.
