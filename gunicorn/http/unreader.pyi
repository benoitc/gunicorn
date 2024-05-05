import socket
from collections.abc import Iterable, Iterator
from typing import IO, Optional

from _typeshed import Incomplete

class Unreader:
    buf: IO[bytes]
    def __init__(self) -> None: ...
    def chunk(self) -> bytes: ...
    def read(self, size: int | None = ...) -> bytes: ...
    def unread(self, data: bytes) -> None: ...

class SocketUnreader(Unreader):
    sock: Incomplete
    mxchunk: Incomplete
    def __init__(self, sock: socket.socket, max_chunk: int = ...) -> None: ...
    def chunk(self) -> bytes: ...

class IterUnreader(Unreader):
    iter: Iterator[bytes]
    def __init__(self, iterable: Iterable[bytes]) -> None: ...
    def chunk(self) -> bytes: ...
