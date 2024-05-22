import importlib.metadata as importlib_metadata
import sys
import typing
from collections.abc import Callable, Iterable
from os import PathLike
from socket import socket
from types import TracebackType
from typing import Any, Protocol, Union

from _typeshed import Incomplete
from _typeshed.wsgi import WSGIApplication
from typing_extensions import LiteralString, NamedTuple

from gunicorn.errors import AppImportError as AppImportError
from gunicorn.glogging import Logger
from gunicorn.workers import SUPPORTED_WORKERS as SUPPORTED_WORKERS
from gunicorn.workers.sync import SyncWorker

if sys.platform.startswith("win"):
    from gunicorn.windows import (
        close_on_exec,
        matching_effective_uid_gid,
        pipe2,
        resolve_gid,
        resolve_uid,
        set_owner_process,
    )
else:
    from gunicorn.unix import (
        close_on_exec,
        matching_effective_uid_gid,
        pipe2,
        resolve_gid,
        resolve_uid,
        set_owner_process,
    )

REDIRECT_TO: str
hop_headers: set[str]

def load_entry_point(
    distribution: str, group: str, name: str
) -> type[Logger] | type[SyncWorker]: ...
def load_class(
    uri: str, default: str = ..., section: str = ...
) -> type[Logger] | type[SyncWorker]: ...

positionals: Incomplete

class _SplitURL(NamedTuple):
    @property
    def port(self) -> int | None: ...
    scheme: str
    netloc: str
    path: str
    query: str
    fragment: str

def _setproctitle(title: str) -> None: ...
def get_arity(f: typing.Callable[..., None]) -> int: ...
def get_username(uid: int) -> str: ...
def chown(path: str | PathLike[str], uid: int, gid: int) -> None: ...
def unlink(filename: str) -> None: ...
def is_ipv6(addr: str) -> bool: ...
def parse_address(netloc: str, default_port: str = ...) -> tuple[str, int]: ...
def close(sock: socket) -> None: ...
def closerange(fd_low: int, fd_high: int) -> None: ...
def write_chunk(sock: socket, data: bytes) -> None: ...
def write(sock: socket, data: bytes, chunked: bool = ...) -> None: ...
def write_nonblock(sock: socket, data: bytes, chunked: bool = ...) -> int: ...
def write_error(
    sock: socket, status_int: int, reason: LiteralString, mesg: str
) -> None: ...
def import_app(module: str) -> WSGIApplication: ...
def getcwd() -> str: ...
def http_date(timestamp: Incomplete | None = ...) -> str: ...
def is_hoppish(header: str) -> bool: ...
def daemonize(enable_stdio_inheritance: bool = ...) -> None: ...
def seed() -> None: ...
def check_is_writable(path: str | PathLike[str]) -> None: ...
def to_bytestring(value: Incomplete, encoding: LiteralString = ...) -> bytes: ...
def has_fileno(obj: Any) -> bool: ...
def warn(msg: LiteralString) -> None: ...
def make_fail_app(msg: str) -> WSGIApplication: ...
def split_request_uri(uri: str) -> _SplitURL: ...
def reraise(
    tp: type[BaseException], value: BaseException, tb: TracebackType | None = ...
) -> None: ...
def bytes_to_str(b: bytes | str) -> str: ...
def unquote_to_wsgi_str(string: bytes) -> str: ...
