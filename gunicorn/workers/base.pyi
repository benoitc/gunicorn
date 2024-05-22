from signal import Signals
from socket import socket
from types import FrameType
from typing import List, TypeAlias

from _typeshed import Incomplete

from gunicorn import util
from gunicorn.app.wsgiapp import WSGIApplication
from gunicorn.config import Config
from gunicorn.glogging import Logger
from gunicorn.http.errors import (
    ForbiddenProxyRequest,
    InvalidHeader,
    InvalidHeaderName,
    InvalidHTTPVersion,
    InvalidProxyLine,
    InvalidRequestLine,
    InvalidRequestMethod,
    InvalidSchemeHeaders,
    LimitRequestHeaders,
    LimitRequestLine,
)
from gunicorn.http.message import Message
from gunicorn.http.wsgi import Response, default_environ
from gunicorn.reloader import reloader_engines
from gunicorn.sock import TCPSocket
from gunicorn.workers.workertmp import WorkerTmp

peer_addr: TypeAlias = tuple[str, int] | str
Pipe: Incomplete

class Worker:
    SIGNALS: Incomplete
    PIPE: list[Pipe]
    age: Incomplete
    pid: str
    ppid: Incomplete
    sockets: Incomplete
    app: Incomplete
    timeout: Incomplete
    cfg: Incomplete
    booted: bool
    aborted: bool
    reloader: Incomplete
    nr: int
    max_requests: Incomplete
    alive: bool
    log: Incomplete
    tmp: Incomplete
    def __init__(
        self,
        age: int,
        ppid: int,
        sockets: list[TCPSocket],
        app: WSGIApplication,
        timeout: float,
        cfg: Config,
        log: Logger,
    ) -> None: ...
    def notify(self) -> None: ...
    def run(self) -> None: ...
    wait_fds: Incomplete
    def init_process(self) -> None: ...
    wsgi: Incomplete
    def load_wsgi(self) -> None: ...
    def init_signals(self) -> None: ...
    def handle_usr1(self, sig: Signals, frame: FrameType | None) -> None: ...
    def handle_exit(self, sig: Signals, frame: FrameType | None) -> None: ...
    def handle_quit(self, sig: Signals, frame: FrameType | None) -> None: ...
    def handle_abort(self, sig: Signals, frame: FrameType | None) -> None: ...
    def handle_error(
        self, req: Message, client: Incomplete, addr: peer_addr, exc: BaseException
    ) -> None: ...
    def handle_winch(self, sig: Signals, fname: FrameType | None) -> None: ...
