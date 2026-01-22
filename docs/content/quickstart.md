# Quickstart

Get a Python web application running with Gunicorn in 5 minutes.

## Install

```bash
pip install gunicorn
```

## Create an Application

Create `app.py`:

=== "Flask"

    ```python
    from flask import Flask

    app = Flask(__name__)

    @app.route("/")
    def hello():
        return "Hello, World!"
    ```

=== "FastAPI"

    ```python
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/")
    def hello():
        return {"message": "Hello, World!"}
    ```

=== "Django"

    Django projects already have a WSGI application at `myproject/wsgi.py`.
    No additional code is needed.

=== "Plain WSGI"

    ```python
    def app(environ, start_response):
        data = b"Hello, World!"
        start_response("200 OK", [
            ("Content-Type", "text/plain"),
            ("Content-Length", str(len(data)))
        ])
        return [data]
    ```

## Run

```bash
gunicorn app:app
```

For Django:

```bash
gunicorn myproject.wsgi
```

For FastAPI (ASGI):

```bash
gunicorn app:app --worker-class asgi
```

## Add Workers

Use multiple workers to handle concurrent requests:

```bash
gunicorn app:app --workers 4
```

A good starting point is `2 * CPU_CORES + 1` workers.

## Bind to a Port

By default Gunicorn binds to `127.0.0.1:8000`. Change it with:

```bash
gunicorn app:app --bind 0.0.0.0:8080
```

## Configuration File

Create `gunicorn.conf.py` for reusable settings:

```python
bind = "0.0.0.0:8000"
workers = 4
accesslog = "-"
```

Then run:

```bash
gunicorn app:app
```

Gunicorn automatically loads `gunicorn.conf.py` from the current directory.

## Next Steps

- [Run](run.md) - Full CLI reference and framework integration
- [Configure](configure.md) - Configuration file options
- [Deploy](deploy.md) - Production deployment with nginx and process managers
- [Settings](reference/settings.md) - Complete settings reference
