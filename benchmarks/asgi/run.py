#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Throughput and latency of gunicorn's native ASGI worker against Uvicorn.

Every variant serves ``apps:app`` with the same Python, event loop (uvloop),
worker count, keep-alive and access-log setting. For each round the
variants run one after the other, in alternating order between rounds, so
a slow drift of the machine does not favour one of them. Each run is
warmed up first, then measured with wrk. During the measurement the
server processes' CPU time and peak RSS are sampled, and wrk's own CPU is
recorded so a client-bound run can be spotted.

Nothing here derives per-request costs from 1/RPS: under concurrency the
two are not comparable. Per-request CPU cost comes from profile_requests.py.

Usage:
    python benchmarks/asgi/run.py                     # all workloads, 5 rounds
    python benchmarks/asgi/run.py --workloads small_keepalive --rounds 9
    python benchmarks/asgi/run.py --label master      # name the result file
"""

import argparse
import datetime
import json
import os
import platform
import resource
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

VARIANTS = {
    "gunicorn-fast": ["{py}", "{launch}", "{root}", "gunicorn", "-k", "asgi", "--http-parser", "fast",
                      "--asgi-loop", "uvloop", "-w", "{workers}", "--keep-alive", "5",
                      "-b", "127.0.0.1:{port}", "apps:app"],
    "gunicorn-python": ["{py}", "{launch}", "{root}", "gunicorn", "-k", "asgi", "--http-parser", "python",
                        "--asgi-loop", "uvloop", "-w", "{workers}", "--keep-alive", "5",
                        "-b", "127.0.0.1:{port}", "apps:app"],
    "uvicorn": ["{py}", "{launch}", "{root}", "uvicorn", "apps:app", "--http", "httptools",
                "--loop", "uvloop", "--workers", "{workers}", "--timeout-keep-alive", "5",
                "--no-access-log", "--host", "127.0.0.1", "--port", "{port}"],
    "gunicorn-uvicorn-worker": ["{py}", "{launch}", "{root}", "gunicorn", "-k", "uvicorn.workers.UvicornWorker",
                                "-w", "{workers}", "--keep-alive", "5",
                                "-b", "127.0.0.1:{port}", "apps:app"],
}

# wrk request setup per workload (Lua). The shared done() hook below
# prints the result as JSON.
_MANY_HEADERS = "".join(
    'wrk.headers["X-Bench-%02d"] = "value-%02d"\n' % (i, i) for i in range(30))
_UPLOAD = 64 * 1024
_CHUNKED_BODY = "".join("%x\\r\\n%s\\r\\n" % (1024, "z" * 1024) for _ in range(8)) + "0\\r\\n\\r\\n"

WORKLOADS = {
    "small_keepalive": 'wrk.path = "/"\n',
    "small_close": 'wrk.path = "/"\nwrk.headers["Connection"] = "close"\n',
    "pct_target": 'wrk.path = "/a%20b/c"\n',
    "many_headers": 'wrk.path = "/"\n' + _MANY_HEADERS,
    "post_upload": ('wrk.method = "POST"\nwrk.path = "/echo"\n'
                    'wrk.body = string.rep("u", %d)\n' % _UPLOAD),
    # wrk adds Content-Length to any request with a body, so a chunked
    # request is written out in full instead.
    "chunked_upload": ('local raw = "POST /echo HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\n" ..\n'
                       '  "Transfer-Encoding: chunked\\r\\n\\r\\n" .. "%s"\n'
                       'request = function() return raw end\n' % _CHUNKED_BODY),
    "large_response": 'wrk.path = "/large"\n',
    "stream_response": 'wrk.path = "/stream"\n',
}

_DONE = """
done = function(summary, latency, requests)
  local e = summary.errors
  io.write(string.format(
    '\\nBENCH_JSON {"requests":%d,"duration_us":%d,"bytes":%d,' ..
    '"errors":{"connect":%d,"read":%d,"write":%d,"status":%d,"timeout":%d},' ..
    '"latency_us":{"p50":%d,"p95":%d,"p99":%d,"max":%d,"mean":%.1f}}\\n',
    summary.requests, summary.duration, summary.bytes,
    e.connect, e.read, e.write, e.status, e.timeout,
    latency:percentile(50), latency:percentile(95), latency:percentile(99),
    latency.max, latency.mean))
end
"""


# Opening a connection per request at full speed runs out of local ports on
# macOS within seconds (TIME_WAIT lasts 30 s there), which measures the
# client, not the server. Run small_close on Linux, or on macOS after
# lowering net.inet.tcp.msl, and ask for it with --workloads.
CLIENT_LIMITED_ON_DARWIN = ("small_close",)


def _default_workloads():
    if sys.platform == "darwin":
        return [w for w in WORKLOADS if w not in CLIENT_LIMITED_ON_DARWIN]
    return list(WORKLOADS)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _tree(proc):
    try:
        return [proc] + proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def _cpu_seconds(procs):
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except psutil.NoSuchProcess:
            pass
    return total


class _RssSampler(threading.Thread):
    def __init__(self, procs):
        super().__init__(daemon=True)
        self.procs = procs
        self.peak = 0
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            rss = 0
            for p in self.procs:
                try:
                    rss += p.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            self.peak = max(self.peak, rss)
            self._halt.wait(0.1)

    def stop(self):
        self._halt.set()
        self.join()


def _wrk(port, script, duration, threads, connections):
    cmd = ["wrk", "-t", str(threads), "-c", str(connections), "-d", "%ds" % duration,
           "-s", script, "http://127.0.0.1:%d" % port]
    # wrk's CPU time: what reaped children used during this call. The server
    # processes are still running, so they are not counted here.
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, check=False).stdout
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    client_cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    for line in out.splitlines():
        if line.startswith("BENCH_JSON "):
            result = json.loads(line[len("BENCH_JSON "):])
            result["client_cpu_s"] = client_cpu
            return result
    raise RuntimeError("wrk gave no result:\n" + out)


def _start(variant, workers, port, root):
    cmd = [part.format(py=sys.executable, launch=os.path.join(HERE, "_launch.py"),
                       root=root, workers=workers, port=port)
           for part in VARIANTS[variant]]
    env = dict(os.environ, PYTHONPATH=HERE)
    proc = psutil.Popen(cmd, cwd=HERE, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait_ready(port):
        proc.kill()
        raise RuntimeError("%s did not start: %s" % (variant, " ".join(cmd)))
    time.sleep(0.5)  # let every worker finish booting
    return proc, cmd


def _stop(proc):
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        for p in _tree(proc):
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass


def _environment(root):
    def version(mod):
        try:
            return __import__(mod).__version__
        except Exception:  # pylint: disable=broad-except
            return None

    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
        except Exception:  # pylint: disable=broad-except
            return None

    wrk_version = subprocess.run(["wrk", "-v"], capture_output=True, text=True, check=False)
    import gunicorn_h1c  # noqa: F401 pylint: disable=import-outside-toplevel,unused-import
    import importlib.metadata as md  # pylint: disable=import-outside-toplevel
    imported = subprocess.check_output(
        [sys.executable, os.path.join(HERE, "_launch.py"), root, "_whichgunicorn"],
        cwd=HERE, text=True).strip()
    return {
        "gunicorn_root": root,
        "gunicorn_imported_from": imported,
        "commit": git("rev-parse", "HEAD"),
        "commit_short": git("rev-parse", "--short", "HEAD"),
        "dirty_tree": bool(git("status", "--porcelain", "--untracked-files=no", "gunicorn")),
        "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": _cpu_name(),
        "cpu_count": os.cpu_count(),
        "versions": {
            "gunicorn": imported and imported.split(" ", 1)[0],
            "gunicorn_h1c": md.version("gunicorn_h1c"),
            "uvicorn": version("uvicorn"),
            "httptools": md.version("httptools"),
            "uvloop": version("uvloop"),
            "wrk": (wrk_version.stdout or wrk_version.stderr).split("\n")[0],
        },
    }


def _cpu_name():
    try:
        if sys.platform == "darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # pylint: disable=broad-except
        pass
    return platform.processor()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    parser.add_argument("--workloads", nargs="+", default=_default_workloads(), choices=list(WORKLOADS))
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--duration", type=int, default=10, help="measured seconds per run")
    parser.add_argument("--warmup", type=int, default=3, help="warm-up seconds per run")
    parser.add_argument("--threads", type=int, default=4, help="wrk threads")
    parser.add_argument("--connections", type=int, default=64, help="wrk connections")
    parser.add_argument("--label", default=None, help="result file name (default: commit)")
    parser.add_argument("--baseline-root", default=None,
                        help="also run the native gunicorn variants from this tree (as "
                             "<variant>@baseline) in the same rounds, interleaved, so a "
                             "change and its baseline see the same machine conditions")
    parser.add_argument("--gunicorn-root", default=REPO,
                        help="gunicorn source tree to benchmark, e.g. a git worktree of "
                             "another revision (default: this checkout)")
    args = parser.parse_args()

    if not shutil.which("wrk"):
        sys.exit("wrk is required (brew install wrk / apt install wrk)")

    root = os.path.abspath(args.gunicorn_root)
    env = _environment(root)
    label = args.label or env["commit_short"]
    # (name, variant, gunicorn tree) for every server started each round
    plan = [(v, v, root) for v in args.variants]
    if args.baseline_root:
        base = os.path.abspath(args.baseline_root)
        env["baseline"] = _environment(base)
        plan += [(v + "@baseline", v, base) for v in args.variants if v.startswith("gunicorn-")
                 and v != "gunicorn-uvicorn-worker"]
    config = {k: getattr(args, k) for k in
              ("variants", "workloads", "rounds", "workers", "duration", "warmup",
               "threads", "connections")}
    runs = []
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        scripts = {}
        for name in args.workloads:
            path = os.path.join(tmp, name + ".lua")
            with open(path, "w") as f:
                f.write(WORKLOADS[name] + _DONE)
            scripts[name] = path

        for rnd in range(args.rounds):
            order = plan if rnd % 2 == 0 else list(reversed(plan))
            for variant, kind, tree in order:
                port = _free_port()
                proc, cmd = _start(kind, args.workers, port, tree)
                try:
                    for workload in args.workloads:
                        procs = _tree(proc)
                        sampler = _RssSampler(procs)
                        try:
                            _wrk(port, scripts[workload], args.warmup, args.threads,
                                 args.connections)
                            sampler.start()
                            cpu0 = _cpu_seconds(procs)
                            result = _wrk(port, scripts[workload], args.duration,
                                          args.threads, args.connections)
                            cpu1 = _cpu_seconds(procs)
                        except RuntimeError as exc:
                            failures.append({"round": rnd, "variant": variant,
                                             "workload": workload, "error": str(exc)})
                            print("round %d %-24s %-16s FAILED: %s" % (
                                rnd, variant, workload, str(exc).splitlines()[-1]), flush=True)
                            continue
                        finally:
                            if sampler.is_alive():
                                sampler.stop()
                        seconds = result["duration_us"] / 1e6
                        result.update({
                            "round": rnd, "variant": variant, "workload": workload,
                            "command": " ".join(cmd),
                            "rps": result["requests"] / seconds,
                            "server_cpu_pct": 100.0 * (cpu1 - cpu0) / seconds,
                            "client_cpu_pct": (100.0 * result["client_cpu_s"] / seconds
                                               if result["client_cpu_s"] is not None else None),
                            "server_peak_rss_mb": sampler.peak / 2**20,
                        })
                        runs.append(result)
                        print("round %d %-24s %-16s %9.0f req/s  p99 %6.2f ms  errors %d" % (
                            rnd, variant, workload, result["rps"],
                            result["latency_us"]["p99"] / 1000,
                            sum(result["errors"].values())), flush=True)
                finally:
                    _stop(proc)

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s.json" % label)
    with open(path, "w") as f:
        json.dump({"label": label, "environment": env, "config": config, "runs": runs,
                   "failures": failures}, f, indent=1)
    print("\nwrote", path)
    print("summary: python benchmarks/asgi/report.py", path)


if __name__ == "__main__":
    main()
