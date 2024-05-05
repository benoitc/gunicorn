from re import Pattern
from typing import BinaryIO, Literal, TypeAlias

from _typeshed import Incomplete

from gunicorn.config import Config
from gunicorn.http.body import Body, ChunkedReader, EOFReader, LengthReader
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
    NoMoreData,
)
from gunicorn.http.unreader import Unreader

MAX_REQUEST_LINE: int
MAX_HEADERS: int
DEFAULT_MAX_HEADERFIELD_SIZE: int

TOKEN_RE: Pattern[str]
METHOD_BADCHAR_RE: Pattern[str]
VERSION_RE: Pattern[str]

PeerAddr: TypeAlias = tuple[str, int] | str

class Message:
    cfg: Config
    unreader: Unreader
    peer_addr: PeerAddr
    remote_addr: PeerAddr
    version: tuple[int, int]
    headers: list[tuple[str, str]]
    trailers: list[tuple[str, str]]
    body: Body | None
    scheme: Literal["https", "http"]
    must_close: bool
    limit_request_fields: Incomplete
    limit_request_field_size: Incomplete
    max_buffer_headers: Incomplete
    def __init__(
        self, cfg: Config, unreader: Unreader, peer_addr: PeerAddr
    ) -> None: ...
    def parse(self, unreader: Unreader) -> None: ...
    def parse_headers(self, data: bytes, from_trailers: bool) -> Incomplete: ...
    def set_body_reader(self) -> None: ...
    def should_close(self) -> bool: ...

class Request(Message):
    method: Incomplete
    uri: Incomplete
    path: Incomplete
    query: Incomplete
    fragment: Incomplete
    limit_request_line: Incomplete
    req_number: Incomplete
    proxy_protocol_info: Incomplete
    def __init__(
        self,
        cfg: Config,
        unreader: Unreader,
        peer_addr: PeerAddr,
        req_number: int = ...,
    ) -> None: ...
    def get_data(
        self, unreader: Config, buf: BinaryIO, stop: bool = ...
    ) -> Incomplete: ...
    headers: Incomplete
    def read_line(
        self, unreader: Unreader, buf: BinaryIO, limit: int = ...
    ) -> Incomplete: ...
    def proxy_protocol(self, line: str) -> Incomplete: ...
    def proxy_protocol_access_check(self) -> None: ...
    def parse_proxy_protocol(self, line: str) -> None: ...
    def parse_request_line(self, line_bytes: bytes) -> None: ...
    def set_body_reader(self) -> None: ...
