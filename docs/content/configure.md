<span id="configuration"></span>
# Configuration Overview

Gunicorn reads configuration from five places, in increasing order of priority:

1. Dedicated environment variables. Only a few settings have these, and they
   are not a general `SETTING=value` overlay:
   `PORT` (default bind address), `WEB_CONCURRENCY` (default worker count),
   `SENDFILE` (sendfile), and `FORWARDED_ALLOW_IPS` (trusted front-end
   addresses). `SENDFILE` is enabled when its value is `y`, `1`, `yes`, or
   `true`, compared case-insensitively.
2. Framework-specific configuration (currently Paste Deploy only).
3. A Python configuration file `gunicorn.conf.py` (default in the working directory).
4. The `GUNICORN_CMD_ARGS` environment variable. Gunicorn splits that value with
   `shlex`, so quoted arguments stay intact, then treats the tokens as extra
   command-line flags.
5. Command-line arguments.

`NOTIFY_SOCKET` is used for systemd readiness notification. It is not a
Gunicorn setting. The control socket default may also follow `XDG_RUNTIME_DIR`.

If a configuration file is provided both via `GUNICORN_CMD_ARGS` and the CLI,
only the file specified on the command line is used.

!!! note
    Print the fully resolved configuration:

    ```bash
    gunicorn --print-config APP_MODULE
    ```

    Validate configuration and exit:

    ```bash
    gunicorn --check-config APP_MODULE
    ```

    This is also a quick way to confirm that your application can start.

## Command line

Options set on the command line override framework settings and values from the
configuration file. Not every setting has a command-line flag; run

```bash
gunicorn -h
```

for the complete list. The CLI also exposes `--version`, which is not part of
the main [settings reference](reference/settings.md).

<span id="configuration_file"></span>
## Configuration file

Provide a Python file (for example `gunicorn.conf.py`). Gunicorn executes the
file on every start or reload, so any valid Python is allowed:

```python
import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
```

Every configuration key is documented in the [settings reference](reference/settings.md).

## Framework settings

At present only Paste Deploy applications expose framework-specific settings.
If you have ideas for Django or other frameworks, open an
[issue](https://github.com/benoitc/gunicorn/issues).

### Paste applications

Reference Gunicorn as the server in your INI file:

```ini
[server:main]
use = egg:gunicorn#main
host = 192.168.0.1
port = 80
workers = 2
proc_name = brim
```

Gunicorn merges any recognised parameters into the base configuration. Values
from the configuration file and command line still override these defaults.
