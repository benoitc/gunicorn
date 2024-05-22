from argparse import ArgumentParser
from collections.abc import Callable
from ssl import (
    CERT_NONE,
    CERT_OPTIONAL,
    PROTOCOL_TLS,
    SSLContext,
    VerifyMode,
    _SSLMethod,
)
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeAlias,
    Union,
    overload,
)

from _typeshed import Incomplete
from typing_extensions import NamedTuple

from gunicorn import __version__ as __version__
from gunicorn import util as util
from gunicorn.arbiter import Arbiter
from gunicorn.errors import ConfigError as ConfigError
from gunicorn.glogging import Logger as Logger
from gunicorn.http import Request
from gunicorn.http.wsgi import Response
from gunicorn.instrument.statsd import Statsd as Statsd
from gunicorn.reloader import reloader_engines as reloader_engines
from gunicorn.workers.base import Worker as Worker

KNOWN_SETTINGS: list[type[Setting]]
PLATFORM: Incomplete

t_pre_request: TypeAlias = Callable[[Worker, Request], None]
t_post_request: TypeAlias = Callable[[Worker, Request, dict[str, str], Response], None]
t_arbiter: TypeAlias = Callable[[Arbiter], None]
t_worker: TypeAlias = Callable[[Worker], None]
t_fork: TypeAlias = Callable[[Arbiter, Worker], None]

def make_settings(ignore: Incomplete | None = ...) -> dict[str, Setting]: ...
def auto_int(_: Umask, x: str) -> int: ...

class _SSLOptions(NamedTuple):
    ssl_version: _SSLMethod
    certfile: str | None
    keyfile: str | None
    cert_reqs: VerifyMode
    ca_certs: str | None
    suppress_ragged_eofs: bool
    do_handshake_on_connect: bool
    ciphers: str | None

class Config:
    settings: Incomplete
    usage: Incomplete
    prog: Incomplete
    env_orig: Incomplete
    def __init__(self, usage: str | None = ..., prog: str | None = ...) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    def __setattr__(self, name: str, value: Any | None) -> None: ...
    def set(self, name: str, value: Any) -> None: ...
    def get_cmd_args_from_env(self) -> list[str]: ...
    def parser(self) -> ArgumentParser: ...
    @property
    def worker_class_str(self) -> str: ...
    @property
    def worker_class(self) -> type[Worker]: ...
    @property
    def address(self) -> list[tuple[str, int]]: ...
    @property
    def uid(self) -> int: ...
    @property
    def gid(self) -> int: ...
    @property
    def proc_name(self) -> str: ...
    @property
    def logger_class(self) -> type[Statsd] | type[Logger]: ...
    @property
    def is_ssl(self) -> str | None: ...
    @property
    def ssl_options(self) -> _SSLOptions: ...
    @property
    def env(self) -> dict[str, str]: ...
    @property
    def sendfile(self) -> bool: ...
    @property
    def reuse_port(self) -> bool: ...
    @property
    def paste_global_conf(self) -> dict[str, Incomplete]: ...

class SettingMeta(type):
    def __new__(
        cls, name: str, bases: tuple[type["Setting"]], attrs: dict[str, Any]
    ) -> Any: ...
    def fmt_desc(cls, desc: str) -> None: ...

class Setting:
    name: str
    value: Incomplete
    section: str
    cli: list[str]
    validator: Callable[..., Incomplete]
    type: Callable[..., Incomplete] | type[Callable[..., Incomplete]] | type[
        int
    ] | type[str]
    meta: str
    action: str
    default: None | bool | int | list[str] | str | Callable[..., Incomplete] | dict[
        str, Incomplete
    ]
    short: str
    desc: str
    nargs: str
    const: bool
    def __init__(self) -> None: ...
    def add_option(self, parser: ArgumentParser) -> None: ...
    def copy(self) -> Setting: ...
    def get(self) -> Any: ...
    def set(self, val: Any) -> None: ...
    def __lt__(self, other: Setting) -> bool: ...
    __cmp__ = __lt__

@overload
def validate_bool(val: None) -> None: ...
@overload
def validate_bool(val: str | bool) -> bool: ...
def validate_dict(val: dict[str, str]) -> dict[str, str]: ...
def validate_pos_int(val: Any) -> int: ...
def validate_ssl_version(val: _SSLMethod | str) -> _SSLMethod | int: ...
@overload
def validate_string(val: None) -> None: ...
@overload
def validate_string(val: str) -> str: ...
@overload
def validate_file_exists(val: None) -> None: ...
@overload
def validate_file_exists(val: str) -> str: ...
def validate_list_string(val: str | list[str]) -> list[str | None]: ...
def validate_list_of_existing_files(val: list[Any]) -> list[Any]: ...
def validate_string_to_list(val: None | str) -> list[str]: ...
def validate_class(val: Incomplete) -> Incomplete: ...
def validate_callable(arity: int) -> Callable[..., Incomplete]: ...
@overload
def validate_user(val: None) -> None: ...
@overload
def validate_user(val: int) -> int: ...
@overload
def validate_group(val: None) -> None: ...
@overload
def validate_group(val: int) -> int: ...
def validate_post_request(val: t_post_request) -> t_post_request: ...
def validate_chdir(val: str) -> str: ...
def validate_statsd_address(val: str | None) -> tuple[str, int] | None: ...
def validate_reload_engine(val: str) -> str: ...
def get_default_config_file() -> str | None: ...

class ConfigFile(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class WSGIApp(Setting):
    name: str
    section: str
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class Bind(Setting):
    name: str
    action: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_list_string
    default: Incomplete
    desc: str

class Backlog(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class Workers(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: Incomplete
    desc: str

class WorkerClass(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_class
    default: str
    desc: str

class WorkerThreads(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class WorkerConnections(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class MaxRequests(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class MaxRequestsJitter(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class Timeout(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class GracefulTimeout(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class Keepalive(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class LimitRequestLine(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class LimitRequestFields(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class LimitRequestFieldSize(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class Reload(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class ReloadEngine(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_reload_engine
    default: str
    desc: str

class ReloadExtraFiles(Setting):
    name: str
    action: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_list_of_existing_files
    default: list[Any]
    desc: str

class Spew(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class ConfigCheck(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class PrintConfig(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class PreloadApp(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class Sendfile(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    const: bool
    desc: str

class ReusePort(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class Chdir(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_chdir
    default: Incomplete
    default_doc: str
    desc: str

class Daemon(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class Env(Setting):
    name: str
    action: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_list_string
    default: list[Any]
    desc: str

class Pidfile(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class WorkerTmpDir(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class User(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_user
    default: None
    value: int | None
    default_doc: str
    desc: str

class Group(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_group
    default: None
    value: int | None
    default_doc: str
    desc: str

class Umask(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_pos_int
    value: int
    default: int
    desc: str

class Initgroups(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class TmpUploadDir(Setting):
    name: str
    section: str
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class SecureSchemeHeader(Setting):
    name: str
    section: str
    validator = validate_dict
    default: dict[str, str]
    desc: str

class ForwardedAllowIPS(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string_to_list
    default: Incomplete
    desc: str

class AccessLog(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class DisableRedirectAccessToSyslog(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class AccessLogFormat(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class ErrorLog(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class Loglevel(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class CaptureOutput(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class LoggerClass(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_class
    default: str
    desc: str

class LogConfig(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class LogConfigDict(Setting):
    name: str
    section: str
    validator = validate_dict
    default: dict[Any, Any]
    desc: str

class LogConfigJson(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class SyslogTo(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class Syslog(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    action: str
    default: bool
    desc: str

class SyslogPrefix(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class SyslogFacility(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: str
    desc: str

class EnableStdioInheritance(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_bool
    default: bool
    action: str
    desc: str

class StatsdHost(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    default: Incomplete
    validator = validate_statsd_address
    desc: str

class DogstatsdTags(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    default: str
    validator = validate_string
    desc: str

class StatsdPrefix(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    default: str
    validator = validate_string
    desc: str

class Procname(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class DefaultProcName(Setting):
    name: str
    section: str
    validator = validate_string
    default: str
    desc: str

class PythonPath(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class Paste(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class OnStarting(Setting):
    name: str
    section: str
    validator: Incomplete
    vallue: Callable[[Arbiter], None]
    @staticmethod
    def on_starting(server: Arbiter) -> None: ...
    default = on_starting
    desc: str

class OnReload(Setting):
    name: str
    section: str
    validator: Incomplete
    value: Callable[[Arbiter], None]
    @staticmethod
    def on_reload(server: Arbiter) -> None: ...
    default = on_reload
    desc: str

class WhenReady(Setting):
    name: str
    section: str
    validator: Incomplete
    value: Callable[[Arbiter], None]
    @staticmethod
    def when_ready(server: Arbiter) -> None: ...
    default = when_ready
    desc: str

class Prefork(Setting):
    name: str
    section: str
    validator: Incomplete
    value: t_fork
    @staticmethod
    def pre_fork(server: Arbiter, worker: Worker) -> None: ...
    default: t_fork = pre_fork
    desc: str

class Postfork(Setting):
    name: str
    section: str
    validator: Incomplete
    value: t_fork
    @staticmethod
    def post_fork(server: Arbiter, worker: Worker) -> None: ...
    default: t_fork
    desc: str

class PostWorkerInit(Setting):
    name: str
    section: str
    validator: Incomplete
    value: t_worker
    default: t_worker
    @staticmethod
    def post_worker_init(worker: Worker) -> None: ...
    desc: str

class WorkerInt(Setting):
    name: str
    section: str
    validator: Incomplete
    value: t_worker
    default: t_worker
    @staticmethod
    def worker_int(worker: Worker) -> None: ...
    desc: str

class WorkerAbort(Setting):
    name: str
    section: str
    validator: Incomplete
    value: t_worker
    default: t_worker
    @staticmethod
    def worker_abort(worker: Worker) -> None: ...
    desc: str

class PreExec(Setting):
    name: str
    section: str
    validator: Incomplete
    @staticmethod
    def pre_exec(server: Arbiter) -> None: ...
    default: t_arbiter
    value: t_arbiter
    desc: str

class PreRequest(Setting):
    name: str
    section: str
    validator: Incomplete
    pre_request: t_pre_request
    default: t_pre_request
    value: t_pre_request
    desc: str

class PostRequest(Setting):
    name: str
    section: str
    validator = validate_post_request
    @staticmethod
    def post_request(
        worker: Worker, req: Request, environ: dict[str, str], resp: Response
    ) -> None: ...
    default: t_post_request
    value: t_post_request
    desc: str

class ChildExit(Setting):
    name: str
    section: str
    validator: Incomplete
    type = callable
    @staticmethod
    def child_exit(server: Arbiter, worker: Worker) -> None: ...
    default: Callable[[Arbiter, Worker], None]
    desc: str

class WorkerExit(Setting):
    name: str
    section: str
    validator: Incomplete
    @staticmethod
    def worker_exit(server: Arbiter, worker: Worker) -> None: ...
    default: t_fork
    value: t_fork
    desc: str

class NumWorkersChanged(Setting):
    name: str
    section: str
    validator: Incomplete
    @staticmethod
    def nworkers_changed(
        server: Arbiter, new_value: int, old_value: int | None
    ) -> None: ...
    default: Callable[[Arbiter, int, int | None], None] = nworkers_changed
    value: Callable[[Arbiter, int, int | None], None]
    desc: str

class OnExit(Setting):
    name: str
    section: str
    validator: Incomplete
    @staticmethod
    def on_exit(server: Arbiter) -> None: ...
    default: t_arbiter
    value: t_arbiter
    desc: str

class NewSSLContext(Setting):
    name: str
    section: str
    validator: Incomplete
    @staticmethod
    def ssl_context(
        config: Config, default_ssl_context_factory: type[SSLContext]
    ) -> SSLContext: ...
    default: Callable[[Config, type[SSLContext]], SSLContext]
    value: Callable[[Config, type[SSLContext]], SSLContext]
    desc: str

class ProxyProtocol(Setting):
    name: str
    section: str
    cli: Incomplete
    default: bool
    value: bool
    action: str
    desc: str

class ProxyAllowFrom(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_string_to_list
    default: str
    desc: str

class KeyFile(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class CertFile(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class SSLVersion(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_ssl_version
    default: Incomplete
    desc: str

class CertReqs(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_pos_int
    default: Incomplete
    desc: str

class CACerts(Setting):
    name: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_string
    default: Incomplete
    desc: str

class SuppressRaggedEOFs(Setting):
    name: str
    section: str
    cli: Incomplete
    action: str
    default: bool
    value: bool
    desc: str

class DoHandshakeOnConnect(Setting):
    name: str
    section: str
    cli: Incomplete
    vallue: bool
    action: str
    default: bool
    desc: str

class Ciphers(Setting):
    name: str
    section: str
    cli: Incomplete
    validator = validate_string
    default: Incomplete
    desc: str

class PasteGlobalConf(Setting):
    name: str
    action: str
    section: str
    cli: Incomplete
    meta: str
    validator = validate_list_string
    default: list[str]
    desc: str

class StripHeaderSpaces(Setting):
    name: str
    section: str
    cli: Incomplete
    value: bool
    action: str
    default: bool
    desc: str
