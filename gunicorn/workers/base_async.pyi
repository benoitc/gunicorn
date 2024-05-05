from contextlib import AbstractAsyncContextManager
from socket import socket
from typing import TypeAlias

from _typeshed import Incomplete

from gunicorn.http.message import Message
from gunicorn.sock import BaseSocket
from gunicorn.workers.base import Worker

ListenInfo: TypeAlias = tuple[str, int] | str | bytes
peer_addr: TypeAlias = tuple[str, int] | str

ALREADY_HANDLED: object

class AsyncWorker(Worker):
    worker_connections: int
    def timeout_ctx(self) -> AbstractAsyncContextManager[None]: ...
    def is_already_handled(self, respiter: Incomplete) -> bool: ...
    def handle(self, listener: BaseSocket, client: socket, addr: peer_addr) -> None: ...
    alive: bool
    def handle_request(
        self, listener_name: ListenInfo, req: Message, sock: BaseSocket, addr: peer_addr
    ) -> bool | None: ...
