from argparse import ArgumentParser, Namespace

from _typeshed import Incomplete
from _typeshed.wsgi import WSGIApplication as _WSGIApplication

from gunicorn import util as util
from gunicorn.app.base import Application as Application
from gunicorn.errors import ConfigError as ConfigError

class WSGIApplication(Application):
    app_uri: Incomplete
    def init(
        self, parser: ArgumentParser, opts: Namespace, args: list[str]
    ) -> None: ...
    def load_config(self) -> None: ...
    def load_wsgiapp(self) -> _WSGIApplication: ...
    def load_pasteapp(self) -> _WSGIApplication: ...
    def load(self) -> _WSGIApplication: ...

def run(prog: str | None = ...) -> None: ...
