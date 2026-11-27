#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Summarize run.py results as markdown.

    python benchmarks/asgi/report.py results/master.json
    python benchmarks/asgi/report.py results/5be13466.json results/master.json

With one file: per workload, every variant's req/s (median, min-max and the
spread as a percentage of the median), latency percentiles (medians of the
rounds), errors, server CPU and peak RSS, and req/s as a share of Uvicorn's.
With several files: median req/s side by side, for comparing revisions.
"""

import json
import re
import statistics
import sys


# Each run listens on its own port; show every command once.
_PORT = re.compile(r"(127\.0\.0\.1:|--port )\d+")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _group(runs):
    groups = {}
    for run in runs:
        groups.setdefault((run["workload"], run["variant"]), []).append(run)
    return groups


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _environment(data):
    env, cfg = data["environment"], data["config"]
    versions = ", ".join("%s %s" % (k, v) for k, v in env["versions"].items() if v)
    lines = [
        "- commit: `%s`%s" % (env["commit"], " (uncommitted changes)" if env["dirty_tree"] else ""),
        "- date: %s" % env["date"],
        "- machine: %s, %s CPUs, %s" % (env["cpu"], env["cpu_count"], env["platform"]),
        "- Python %s; %s" % (env["python"], versions),
        "- %d worker(s); wrk -t%d -c%d; %ds measured after %ds warm-up; %d rounds, "
        "variant order alternating" % (
            cfg["workers"], cfg["threads"], cfg["connections"],
            cfg["duration"], cfg["warmup"], cfg["rounds"]),
    ]
    commands = sorted({r["variant"] + ": `" + _PORT.sub(r"\1PORT", r["command"]) + "`"
                       for r in data["runs"]})
    lines.append("- commands:")
    lines.extend("  - " + c for c in commands)
    return "\n".join(lines)


def single(data):
    out = ["# ASGI benchmark: %s" % data["label"], "", _environment(data), ""]
    groups = _group(data["runs"])
    workloads = list(dict.fromkeys(r["workload"] for r in data["runs"]))
    variants = list(dict.fromkeys(r["variant"] for r in data["runs"]))
    for workload in workloads:
        base = groups.get((workload, "uvicorn"))
        base_rps = _median([r["rps"] for r in base]) if base else None
        out += ["## %s" % workload, "",
                "| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms "
                "| p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for variant in variants:
            runs = groups.get((workload, variant))
            if not runs:
                continue
            rps = [r["rps"] for r in runs]
            med = statistics.median(rps)
            spread = 100.0 * (max(rps) - min(rps)) / med if med else 0.0
            ratio = "%.0f%%" % (100.0 * med / base_rps) if base_rps else "-"
            baseline_runs = groups.get((workload, variant + "@baseline"))
            if baseline_runs:
                b = statistics.median([r["rps"] for r in baseline_runs])
                vs_base = "%+.1f%%" % (100.0 * (med - b) / b)
            else:
                vs_base = "-"
            lat = {k: _median([r["latency_us"][k] for r in runs]) / 1000
                   for k in ("p50", "p95", "p99")}
            errors = sum(sum(r["errors"].values()) for r in runs)
            out.append("| %s | %.0f | %.0f-%.0f | %.1f%% | %s | %s | %.2f | %.2f | %.2f | %d | %.0f | %s | %.0f |" % (
                variant, med, min(rps), max(rps), spread, ratio, vs_base,
                lat["p50"], lat["p95"], lat["p99"], errors,
                _median([r["server_cpu_pct"] for r in runs]),
                "%.0f" % _median([r["client_cpu_pct"] for r in runs])
                if _median([r["client_cpu_pct"] for r in runs]) is not None else "-",
                max(r["server_peak_rss_mb"] for r in runs)))
        out.append("")
    return "\n".join(out)


def compare(datas):
    labels = [d["label"] for d in datas]
    out = ["# ASGI benchmark comparison: %s" % " vs ".join(labels), ""]
    for d in datas:
        out += ["### %s" % d["label"], "", _environment(d), ""]
    keys = []
    for d in datas:
        for r in d["runs"]:
            if (r["workload"], r["variant"]) not in keys:
                keys.append((r["workload"], r["variant"]))
    out += ["| workload | variant | " + " | ".join("%s req/s" % label for label in labels)
            + " | change |", "|---|---|" + "---|" * len(labels) + "---|"]
    for workload, variant in keys:
        meds = []
        for d in datas:
            runs = _group(d["runs"]).get((workload, variant))
            meds.append(statistics.median([r["rps"] for r in runs]) if runs else None)
        change = ("%+.1f%%" % (100.0 * (meds[-1] - meds[0]) / meds[0])
                  if meds[0] and meds[-1] else "-")
        out.append("| %s | %s | %s | %s |" % (
            workload, variant, " | ".join("%.0f" % m if m else "-" for m in meds), change))
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    datas = [_load(p) for p in sys.argv[1:]]
    print(single(datas[0]) if len(datas) == 1 else compare(datas))


if __name__ == "__main__":
    main()
