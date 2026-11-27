#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Per-request CPU and allocation cost of the native ASGI path, in process.

Runs requests through gunicorn's real ASGIProtocol (real Config and
Logger, access log off unless --access-log) over an in-memory transport,
one request at a time on a kept-alive connection, so the numbers are the
Python cost of one request with no network or client in the way. Uvicorn's
httptools protocol is driven the same way for comparison.

Each measurement is a separate pass, never mixed with another:
    time        median microseconds per request over several batches
    calls       Python and C calls per request (sys.setprofile)
    cprofile    the functions with the most own time
    memory      memory still held after a batch (leak check) and peak
                traced memory during it (tracemalloc)

Usage:
    python benchmarks/asgi/profile_requests.py
    python benchmarks/asgi/profile_requests.py --servers gunicorn-fast --top 25
    python benchmarks/asgi/profile_requests.py --request many_headers
    python benchmarks/asgi/profile_requests.py --request large --count 300
"""

import argparse
import asyncio
import cProfile
import io
import os
import pstats
import statistics
import sys
import time
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from apps import app  # noqa: E402

REQUESTS = {
    "small": b"GET / HTTP/1.1\r\nHost: localhost\r\nUser-Agent: bench\r\nAccept: */*\r\n\r\n",
    "pct_target": b"GET /a%20b/c HTTP/1.1\r\nHost: localhost\r\nAccept: */*\r\n\r\n",
    "many_headers": (b"GET / HTTP/1.1\r\nHost: localhost\r\n"
                     + b"".join(b"X-Bench-%02d: value-%02d\r\n" % (i, i) for i in range(30))
                     + b"\r\n"),
    "stream": b"GET /stream HTTP/1.1\r\nHost: localhost\r\nAccept: */*\r\n\r\n",
    "large": b"GET /large HTTP/1.1\r\nHost: localhost\r\nAccept: */*\r\n\r\n",
}

# How each response of apps.app ends: the small body, the chunked
# terminator of /stream, or the last bytes of the 1 MiB /large body.
_RESPONSE_ENDS = (b"Hello, World!", b"0\r\n\r\n", b"x" * 32)


class _Transport(asyncio.Transport):  # pylint: disable=abstract-method
    """Drops writes; signals each complete response."""

    def __init__(self, loop):
        super().__init__()
        self._loop = loop
        self.responses = 0
        self.waiter = None
        self._extra = {"peername": ("127.0.0.1", 40000),
                       "sockname": ("127.0.0.1", 8000), "ssl_object": None}

    def get_extra_info(self, name, default=None):
        return self._extra.get(name, default)

    def write(self, data):
        if data.endswith(_RESPONSE_ENDS):
            self.responses += 1
            if self.waiter is not None and not self.waiter.done():
                self.waiter.set_result(None)

    def writelines(self, list_of_data):
        # Like uvloop's, without joining (which would copy the buffers).
        self.write(list_of_data[-1])

    def is_closing(self):
        return False

    def close(self):
        pass

    def pause_reading(self):
        pass

    def resume_reading(self):
        pass

    def set_write_buffer_limits(self, high=None, low=None):
        pass

    def get_write_buffer_size(self):
        return 0

    def can_write_eof(self):
        return False


def _gunicorn_protocol(loop, transport, parser, access_log):
    from gunicorn.asgi.protocol import ASGIProtocol
    from gunicorn.config import Config
    from gunicorn.glogging import Logger

    cfg = Config()
    cfg.set("http_parser", parser)
    cfg.set("keepalive", 30)
    if access_log:
        cfg.set("accesslog", os.devnull)

    class _Worker:
        pass

    worker = _Worker()
    worker.cfg = cfg
    worker.loop = loop
    worker.log = Logger(cfg)
    worker.asgi = app
    worker.nr_conns = 0
    worker.nr = 0
    worker.max_requests = sys.maxsize  # what the worker uses when max_requests is 0
    worker.alive = True
    proto = ASGIProtocol(worker)
    proto.connection_made(transport)
    return proto


def _uvicorn_protocol(loop, transport, access_log):
    from uvicorn.config import Config
    from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
    from uvicorn.server import ServerState

    config = Config(app, http="httptools", loop="none", lifespan="off",
                    access_log=access_log, log_level="warning")
    config.load()
    proto = HttpToolsProtocol(config=config, server_state=ServerState(),
                              app_state={}, _loop=loop)
    proto.connection_made(transport)
    return proto


SERVERS = {
    "gunicorn-fast": lambda loop, t, a: _gunicorn_protocol(loop, t, "fast", a),
    "gunicorn-python": lambda loop, t, a: _gunicorn_protocol(loop, t, "python", a),
    "uvicorn": _uvicorn_protocol,
}


async def _serve(proto, transport, request, count):
    loop = asyncio.get_running_loop()
    for _ in range(count):
        transport.waiter = loop.create_future()
        proto.data_received(request)
        await transport.waiter


def _close(loop, proto):
    """Cancel what the connection left running, then close the loop."""
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()
    del proto


_NEW_LOOP = asyncio.new_event_loop
LOOP_NAME = "asyncio"


def _make(server, access_log):
    loop = _NEW_LOOP()
    asyncio.set_event_loop(loop)
    transport = _Transport(loop)
    proto = SERVERS[server](loop, transport, access_log)
    return loop, proto, transport


def measure_time(server, request, count, batches, access_log):
    loop, proto, transport = _make(server, access_log)
    loop.run_until_complete(_serve(proto, transport, request, 2000))  # warm-up
    per_request = []
    for _ in range(batches):
        start = time.perf_counter()
        loop.run_until_complete(_serve(proto, transport, request, count))
        per_request.append((time.perf_counter() - start) / count * 1e6)
    _close(loop, proto)
    return statistics.median(per_request), min(per_request), max(per_request)


def measure_calls(server, request, count, access_log):
    loop, proto, transport = _make(server, access_log)
    loop.run_until_complete(_serve(proto, transport, request, 200))
    calls = {"py": 0, "c": 0}

    def tracer(frame, event, arg):  # pylint: disable=unused-argument
        if event == "call":
            calls["py"] += 1
        elif event == "c_call":
            calls["c"] += 1

    sys.setprofile(tracer)
    try:
        loop.run_until_complete(_serve(proto, transport, request, count))
    finally:
        sys.setprofile(None)
    _close(loop, proto)
    return calls["py"] / count, calls["c"] / count


def measure_cprofile(server, request, count, top, access_log):
    loop, proto, transport = _make(server, access_log)
    loop.run_until_complete(_serve(proto, transport, request, 200))
    prof = cProfile.Profile()
    prof.enable()
    loop.run_until_complete(_serve(proto, transport, request, count))
    prof.disable()
    _close(loop, proto)
    out = io.StringIO()
    pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(top)
    return out.getvalue()


def measure_alloc(server, request, count, access_log):
    """Memory still held after ``count`` requests (a leak check), and the
    peak of traced memory while they ran.

    tracemalloc snapshots only show what is still allocated at the end, not
    how many allocations a request made; call counts and cProfile are the
    better guide to per-request object churn.
    """
    loop, proto, transport = _make(server, access_log)
    loop.run_until_complete(_serve(proto, transport, request, 200))
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    tracemalloc.reset_peak()
    loop.run_until_complete(_serve(proto, transport, request, count))
    _, peak = tracemalloc.get_traced_memory()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    retained = sum(s.size_diff for s in after.compare_to(before, "filename"))
    _close(loop, proto)
    return retained, peak


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--servers", nargs="+", default=list(SERVERS), choices=list(SERVERS))
    parser.add_argument("--request", default="small", choices=list(REQUESTS))
    parser.add_argument("--count", type=int, default=20000, help="requests per batch")
    parser.add_argument("--batches", type=int, default=7)
    parser.add_argument("--top", type=int, default=0, help="print cProfile top N (0: skip)")
    parser.add_argument("--access-log", action="store_true")
    parser.add_argument("--gunicorn-root", default=os.path.dirname(os.path.dirname(HERE)),
                        help="gunicorn source tree to profile (default: this checkout)")
    args = parser.parse_args()

    # An editable install wins over PYTHONPATH; put the tree asked for first.
    sys.path.insert(0, os.path.abspath(args.gunicorn_root))
    import gunicorn  # pylint: disable=import-outside-toplevel

    global _NEW_LOOP, LOOP_NAME  # pylint: disable=global-statement
    try:
        import uvloop  # pylint: disable=import-outside-toplevel
        _NEW_LOOP = uvloop.new_event_loop
        LOOP_NAME = "uvloop"
    except ImportError:
        pass

    request = REQUESTS[args.request]
    print("gunicorn %s from %s" % (gunicorn.__version__, os.path.dirname(gunicorn.__file__)))
    print("request: %s; event loop: %s; Python %s; access log %s" % (
        args.request, LOOP_NAME, sys.version.split()[0], "on" if args.access_log else "off"))
    print("%-16s %10s %14s %9s %8s %8s %13s %10s" % (
        "server", "us/req", "min-max", "py calls", "C calls", "total", "retained B", "peak KiB"))
    for server in args.servers:
        med, lo, hi = measure_time(server, request, args.count, args.batches, args.access_log)
        py_calls, c_calls = measure_calls(server, request, 2000, args.access_log)
        retained, peak = measure_alloc(server, request, 2000, args.access_log)
        print("%-16s %10.2f %14s %9.1f %8.1f %8.1f %13d %10.1f" % (
            server, med, "%.2f-%.2f" % (lo, hi), py_calls, c_calls, py_calls + c_calls,
            retained, peak / 1024), flush=True)
    if args.top:
        for server in args.servers:
            print("\n== cProfile, %s, %d requests ==" % (server, 5000))
            print(measure_cprofile(server, request, 5000, args.top, args.access_log))


if __name__ == "__main__":
    main()
