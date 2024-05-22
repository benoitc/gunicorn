import socket
from collections.abc import Mapping
from datetime import datetime
from logging import Logger as _Logger
from logging.config import _DictConfigArgs
from threading import Lock
from typing import Any, Literal

from _typeshed import Incomplete

from gunicorn.config import Config
from gunicorn.http.message import Message
from gunicorn.http.wsgi import Response

SYSLOG_FACILITIES: dict[str, int]
CONFIG_DEFAULTS: _DictConfigArgs

def loggers() -> list[_Logger]: ...

class SafeAtoms(dict[str, Incomplete]):
    def __init__(self, atoms: dict[str, Incomplete]) -> None: ...
    def __getitem__(self, k: str) -> Incomplete: ...

def parse_syslog_address(addr: str) -> tuple[socket.SocketKind, tuple[str, int]]: ...

class Logger:
    LOG_LEVELS: Incomplete
    loglevel: Incomplete
    error_fmt: str
    datefmt: str
    access_fmt: str
    syslog_fmt: str
    atoms_wrapper_class = SafeAtoms
    error_log: Incomplete
    access_log: Incomplete
    error_handlers: Incomplete
    access_handlers: Incomplete
    logfile: Incomplete
    lock: Lock
    cfg: Config
    def __init__(self, cfg: Config) -> None: ...
    def setup(self, cfg: Config) -> None: ...
    def critical(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def warning(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def info(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def debug(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def exception(self, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def log(self, lvl: str, msg: str, *args: Any, **kwargs: dict[str, Any]) -> None: ...
    def atoms(
        self,
        resp: Response,
        req: Message,
        environ: Mapping[str, str],
        request_time: datetime,
    ) -> Incomplete: ...
    def access(
        self,
        resp: Response,
        req: Message,
        environ: Mapping[str, str],
        request_time: datetime,
    ) -> None: ...
    def now(self) -> str: ...
    def reopen_files(self) -> None: ...
    def close_on_exec(self) -> None: ...
