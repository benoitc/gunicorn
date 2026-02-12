<span id="configuration"></span>
# Configuration Overview

Gunicorn reads configuration from five places, in increasing order of priority:

1. Environment variables, for settings that support them.
2. Framework-specific configuration (currently Paste Deploy only).
3. A Python configuration file `gunicorn.conf.py` (default in the working directory).
4. The `GUNICORN_CMD_ARGS` environment variable.
5. Command-line arguments.

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
