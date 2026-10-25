#!/usr/bin/env python3
"""Compare two benchmark result files (JSON lines from bench.py) as a Markdown table.

Usage: python3 bench/report.py bench/results/baseline.jsonl bench/results/after.jsonl
"""
import json
import sys


def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            kind = "switch" if r["label"].endswith("-switch") else r["mode"]
            rows[(kind, r["concurrency"])] = r
    return rows


def fmt(v):
    return "—" if v is None else f"{v:g}"


def ratio(a, b):
    if not a or not b:
        return "—"
    return f"**{a / b:.1f}×**"


def main(base_path, new_path):
    base, new = load(base_path), load(new_path)
    print(f"| Scenario | Conc. | TTFB p50 before → after (ms) | p50 gain | TTFB p99 before → after (ms) | p99 gain | Errors before → after | RPS before → after |")
    print("|---|---|---|---|---|---|---|---|")
    for key in sorted(set(base) | set(new), key=lambda k: (k[0], k[1])):
        b, n = base.get(key, {}), new.get(key, {})
        bt, nt = b.get("ttfb", {}), n.get("ttfb", {})
        be = sum(b.get("errors", {}).values()) if b else None
        ne = sum(n.get("errors", {}).values()) if n else None
        print(
            f"| {key[0]} | {key[1]} | {fmt(bt.get('p50'))} → {fmt(nt.get('p50'))} | {ratio(bt.get('p50'), nt.get('p50'))} "
            f"| {fmt(bt.get('p99'))} → {fmt(nt.get('p99'))} | {ratio(bt.get('p99'), nt.get('p99'))} "
            f"| {fmt(be)} → {fmt(ne)} | {fmt(b.get('rps'))} → {fmt(n.get('rps'))} |"
        )


if __name__ == "__main__":
    main(*sys.argv[1:3])
