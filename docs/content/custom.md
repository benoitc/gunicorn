<span id="custom"></span>
# Custom Application

!!! info "Added in 19.0"
    Use Gunicorn as part of your own WSGI application by subclassing
    `gunicorn.app.base.BaseApplication`.



Example: create a tiny WSGI app and load it with a custom application:

```text
--8<-- "examples/standalone_app.py"
```



## Using server hooks

Provide hooks through configuration, just like a standard Gunicorn deployment.
For example, a `pre_fork` hook:

```python
def pre_fork(server, worker):
    print(f"pre-fork server {server} worker {worker}", file=sys.stderr)

if __name__ == "__main__":
    options = {
        "bind": "127.0.0.1:8080",
        "workers": number_of_workers(),
        "pre_fork": pre_fork,
    }
```

## Direct usage of existing WSGI apps

Run Gunicorn from Python to serve a WSGI application instance at runtime—useful
for rolling deploys or packaging with PEX. Gunicorn exposes
`gunicorn.app.wsgiapp`, which accepts any WSGI app (for example a Flask or
Django instance). Assuming your package is `exampleapi` and the application is
`app`:

```bash
python -m gunicorn.app.wsgiapp exampleapi:app
```

All CLI flags and configuration files still apply:

```bash
# Custom parameters
python -m gunicorn.app.wsgiapp exampleapi:app --bind=0.0.0.0:8081 --workers=4
# Using a config file
python -m gunicorn.app.wsgiapp exampleapi:app -c config.py
```

For PEX builds use `-c gunicorn` at build time so the packaged app accepts the
entry point at runtime:

```bash
pex . -v -c gunicorn -o compiledapp.pex
./compiledapp.pex exampleapi:app -c gunicorn_config.py
```
