from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from selectors import BaseSelector
from signal import Signals
from types import FrameType
from typing import Type, TypeAlias

from _typeshed import Incomplete
from typing_extensions import Self

from gunicorn.config import Config
from gunicorn.glogging import Logger
from gunicorn.http.message import Message
from gunicorn.sock import BaseSocket

from .base import Worker

PeerAddr: TypeAlias = tuple[str, int] | str | bytes
_future_sig = Callable[[BaseSocket], tuple[bool, BaseSocket]]

class TConn:
    cfg: Incomplete
    sock: Incomplete
    client: Incomplete
    server: Incomplete
    timeout: Incomplete
    parser: Incomplete
    initialized: bool
    def __init__(
        self, cfg: Config, sock: BaseSocket, client: PeerAddr, server: PeerAddr
    ) -> None: ...
    def init(self) -> None: ...
    def set_timeout(self) -> None: ...
    def close(self) -> None: ...

class ThreadWorker(Worker):
    worker_connections: Incomplete
    max_keepalived: int
    tpool: ThreadPoolExecutor
    poller: BaseSelector
    futures: deque[Future[_future_sig]]
    _keep: deque[BaseSocket]
    nr_conns: int
    @classmethod
    def check_config(cls: type[Self], cfg: Config, log: Logger) -> None: ...
    def init_process(self) -> None: ...
    def get_thread_pool(self) -> ThreadPoolExecutor: ...
    alive: bool
    def handle_quit(self, sig: Signals, frame: FrameType | None) -> None: ...
    def _wrap_future(self, fs: Future[_future_sig], conn: BaseSocket) -> None: ...
    def enqueue_req(self, conn: BaseSocket) -> None: ...
    def accept(self, server: PeerAddr, listener: BaseSocket) -> None: ...
    def on_client_socket_readable(self, conn: BaseSocket, client: PeerAddr) -> None: ...
    def murder_keepalived(self) -> None: ...
    def is_parent_alive(self) -> bool: ...
    def run(self) -> None: ...
    def finish_request(self, fs: Future[_future_sig]) -> None: ...
    def handle(self, conn: BaseSocket) -> tuple[bool, BaseSocket]: ...
    def handle_request(self, req: Message, conn: BaseSocket) -> bool: ...
