from gunicorn.http.errors import ObsoleteFolding

cfg.set('permit_obsolete_folding', True)

request = {
    "method": "GET",
    "uri": uri("/"),
    "version": (1, 1),
    "headers": [
        ("LONG", "one two"),
        ("HOST", "localhost"),
    ],
    "body": b"",
}
