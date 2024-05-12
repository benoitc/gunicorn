from contextlib import AbstractAsyncContextManager
from signal import Signals
from socket import socket
from types import FrameType
from typing import Type, TypeAlias

from _typeshed import Incomplete
from _typeshed.wsgi import StartResponse, WSGIEnvironment
from gevent import pywsgi

from gunicorn.http.message import Message
from gunicorn.sock import BaseSocket
from gunicorn.workers.base_async import AsyncWorker

ListenInfo: TypeAlias = tuple[str, int] | str | bytes
peer_addr: TypeAlias = tuple[str, int] | str

VERSION: str

class GeventWorker(AsyncWorker):
    server_class: type[PyWSGIServer]
    wsgi_handler: type[PyWSGIHandler]
    sockets: Incomplete
    def patch(self) -> None: ...
    def notify(self) -> None: ...
    def timeout_ctx(self) -> AbstractAsyncContextManager[None]: ...
    def run(self) -> None: ...
    def handle(self, listener: BaseSocket, client: socket, addr: peer_addr) -> None: ...
    def handle_request(
        self, listener_name: ListenInfo, req: Message, sock: BaseSocket, addr: peer_addr
    ) -> None: ...
    def handle_quit(self, sig: Signals, frame: FrameType | None) -> None: ...
    def handle_usr1(self, sig: Signals, frame: FrameType | None) -> None: ...
    def init_process(self) -> None: ...

class GeventResponse:
    status: str
    headers: list[tuple[str, str]]
    sent: int
    def __init__(
        self, status: int, headers: list[tuple[str, str]], clength: int
    ) -> None: ...

class PyWSGIHandler(pywsgi.WSGIHandler):
    status: bytes
    response_headers: list[tuple[bytes, bytes]]

    def log_request(self) -> None: ...
    def get_environ(self) -> WSGIEnvironment: ...

class PyWSGIServer(pywsgi.WSGIServer): ...

class GeventPyWSGIWorker(GeventWorker):
    server_class = PyWSGIServer
    wsgi_handler = PyWSGIHandler
