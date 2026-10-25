#!/usr/bin/env python3
"""Latency benchmark for an HTTP proxy (stdlib only).

Each request goes through the proxy with CONNECT, optionally TLS to the target, then a GET.
Per request it records:
  connect  - TCP connect to the proxy
  tunnel   - CONNECT answered (note: sing-box answers before dialing the node, so ttfb is the metric to watch)
  ttfb     - first response byte, measured from the start of the request
Modes:
  new    - a fresh tunnel for every request (worst case: full handshake chain each time)
  reuse  - each worker keeps one tunnel open and sends keep-alive requests over it

Example:
  python3 bench.py --proxy 127.0.0.1:8081 --target target:80 -n 500 -c 50 --mode new --json out.json
"""
import argparse
import asyncio
import base64
import json
import ssl
import statistics
import time


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


async def read_response(reader):
    """Read one HTTP/1.1 response; returns (status, time of first byte)."""
    first = await reader.readline()
    t_first = time.perf_counter()
    if not first:
        raise ConnectionError("connection closed before response")
    status = int(first.split()[1])
    length, chunked = 0, False
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b""):
            break
        name, _, value = line.decode("latin-1").partition(":")
        name = name.strip().lower()
        if name == "content-length":
            length = int(value.strip())
        elif name == "transfer-encoding" and "chunked" in value.lower():
            chunked = True
    if chunked:
        while True:
            size = int((await reader.readline()).strip() or b"0", 16)
            await reader.readexactly(size + 2)
            if size == 0:
                break
    elif length:
        await reader.readexactly(length)
    return status, t_first


async def open_tunnel(args):
    t0 = time.perf_counter()
    host, port = args.proxy.rsplit(":", 1)
    reader, writer = await asyncio.open_connection(host, int(port))
    t_connect = time.perf_counter()
    auth = ""
    if args.user:
        token = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
        auth = f"Proxy-Authorization: Basic {token}\r\n"
    writer.write(f"CONNECT {args.target} HTTP/1.1\r\nHost: {args.target}\r\n{auth}\r\n".encode())
    await writer.drain()
    line = await reader.readline()
    if b" 200" not in line:
        raise ConnectionError(f"CONNECT failed: {line!r}")
    while (await reader.readline()) not in (b"\r\n", b""):
        pass
    t_tunnel = time.perf_counter()
    if args.tls:
        ctx = ssl.create_default_context()
        if args.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        await writer.start_tls(ctx, server_hostname=args.target.rsplit(":", 1)[0])
    return reader, writer, t0, t_connect, t_tunnel


async def send_get(reader, writer, args):
    host = args.target.rsplit(":", 1)[0]
    writer.write(f"GET {args.path} HTTP/1.1\r\nHost: {host}\r\nConnection: keep-alive\r\n\r\n".encode())
    await writer.drain()
    return await read_response(reader)


async def run(args):
    results = []  # dicts: connect, tunnel, ttfb (ms) or error
    remaining = args.requests
    lock = asyncio.Lock()

    async def take():
        nonlocal remaining
        async with lock:
            if remaining <= 0:
                return False
            remaining -= 1
            return True

    async def worker_new():
        while await take():
            writer = None
            try:
                reader, writer, t0, tc, tt = await asyncio.wait_for(open_tunnel(args), args.timeout)
                status, tf = await asyncio.wait_for(send_get(reader, writer, args), args.timeout)
                results.append({"connect": (tc - t0) * 1e3, "tunnel": (tt - t0) * 1e3, "ttfb": (tf - t0) * 1e3, "status": status})
            except Exception as e:  # noqa: BLE001 - every failure is a data point
                results.append({"error": type(e).__name__})
            finally:
                if writer:
                    writer.close()

    async def worker_reuse():
        reader = writer = None
        while await take():
            try:
                if writer is None:
                    reader, writer, *_ = await asyncio.wait_for(open_tunnel(args), args.timeout)
                t0 = time.perf_counter()
                status, tf = await asyncio.wait_for(send_get(reader, writer, args), args.timeout)
                results.append({"ttfb": (tf - t0) * 1e3, "status": status})
            except Exception as e:  # noqa: BLE001
                results.append({"error": type(e).__name__})
                if writer:
                    writer.close()
                reader = writer = None
        if writer:
            writer.close()

    worker = worker_new if args.mode == "new" else worker_reuse
    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    elapsed = time.perf_counter() - started

    ok = [r for r in results if "error" not in r]
    errors = {}
    for r in results:
        if "error" in r:
            errors[r["error"]] = errors.get(r["error"], 0) + 1
    summary = {
        "label": args.label,
        "mode": args.mode,
        "concurrency": args.concurrency,
        "requests": len(results),
        "ok": len(ok),
        "errors": errors,
        "rps": round(len(ok) / elapsed, 1) if elapsed else None,
    }
    for key in ("connect", "tunnel", "ttfb"):
        vals = [r[key] for r in ok if key in r]
        if vals:
            summary[key] = {
                "p50": round(pct(vals, 50), 1),
                "p95": round(pct(vals, 95), 1),
                "p99": round(pct(vals, 99), 1),
                "mean": round(statistics.fmean(vals), 1),
            }
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True, help="host:port of the HTTP proxy")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--target", required=True, help="host:port to CONNECT to")
    ap.add_argument("--path", default="/")
    ap.add_argument("--tls", action="store_true", help="TLS to the target inside the tunnel")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("-n", "--requests", type=int, default=200)
    ap.add_argument("-c", "--concurrency", type=int, default=10)
    ap.add_argument("--mode", choices=("new", "reuse"), default="new")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--label", default="")
    ap.add_argument("--json", help="append the summary as one JSON line to this file")
    args = ap.parse_args()
    summary = asyncio.run(run(args))
    print(json.dumps(summary))
    if args.json:
        with open(args.json, "a") as f:
            f.write(json.dumps(summary) + "\n")


if __name__ == "__main__":
    main()
