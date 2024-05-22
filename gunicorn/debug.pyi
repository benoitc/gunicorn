from collections.abc import Container
from types import FrameType
from typing import Any, Literal

from _typeshed import Incomplete
from typing_extensions import Self

class Spew:
    trace_names: Incomplete
    show_values: Incomplete
    def __init__(
        self, trace_names: Container[str] | None = ..., show_values: bool = ...
    ) -> None: ...
    def __call__(
        self,
        frame: FrameType,
        event: Literal["call", "line", "return", "exception", "opcode"],
        arg: Any,
    ) -> Self: ...

def spew(trace_names: Container[str] | None = ..., show_values: bool = ...) -> None: ...
def unspew() -> None: ...
