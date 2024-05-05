from _typeshed import Incomplete
from typing_extensions import Self

from gunicorn.config import Config as Config
from gunicorn.http.message import Request as Request
from gunicorn.http.unreader import IterUnreader as IterUnreader
from gunicorn.http.unreader import SocketUnreader as SocketUnreader

class Parser:
    mesg_class: type[Request] | None
    cfg: Incomplete
    unreader: Incomplete
    mesg: Incomplete
    source_addr: Incomplete
    req_count: int
    def __init__(self, cfg: Config, source: str, source_addr: str) -> None: ...
    def __iter__(self) -> Self: ...
    def __next__(self) -> Request: ...
    next = __next__

class RequestParser(Parser):
    mesg_class = Request
