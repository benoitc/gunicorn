import threading
from collections.abc import Callable, Iterable
from re import Pattern
from typing import TypeAlias

from _typeshed import Incomplete

COMPILED_EXT_RE: Pattern[str]

reloader_cb: TypeAlias = Callable[[str], None]

class Reloader(threading.Thread):
    daemon: bool
    def __init__(
        self,
        extra_files: Incomplete | None = ...,
        interval: int = ...,
        callback: Incomplete | None = ...,
    ) -> None: ...
    def add_extra_file(self, filename: str) -> None: ...
    def get_files(self) -> list[str]: ...
    def run(self) -> None: ...

has_inotify: bool

# ignoring duplicate - that one is guaranteed to error on actual use
class InotifyReloader(threading.Thread):
    event_mask: int
    daemon: bool
    def __init__(
        self,
        extra_files: Iterable[str] | None = ...,
        callback: reloader_cb | None = ...,
    ) -> None: ...
    def add_extra_file(self, filename: str) -> None: ...
    def get_dirs(self) -> list[str]: ...
    def run(self) -> None: ...

preferred_reloader: type[InotifyReloader] | type[Reloader]
reloader_engines: dict[str, type[InotifyReloader] | type[Reloader]]
