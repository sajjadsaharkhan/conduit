# Performance: latency under heavy load

What Conduit does by default, what you can turn on, and what has to change on your servers.
Measure every change with the benchmark at the end of this page.

## Where the time goes

A new HTTPS request through a WebSocket+TLS node, with round-trip time **R** to the node:

| Step | Cost | Removed by |
|---|---|---|
| TCP handshake to the node | 1 R | Multiplex (warm connection) or TCP Fast Open |
| TLS handshake to the node | 1 R | Multiplex |
| WebSocket upgrade | 1 R | Multiplex, or WebSocket early data on the Xray core (`?ed=2048`) |
| Request and response | 1 R | — (set by distance to the node) |

On an open connection only the last row is left. No setting changes that; a closer node does.

## Built in, nothing to configure

- **Live node switching (sing-box).** All nodes are in the config behind a `selector`. "Use" switches it
  through the Clash API on `127.0.0.1:9092`: no restart, open connections keep running, warm pools stay warm.
  Adding, editing or deleting nodes still restarts the core. Xray restarts on every switch.
- **`?ed=` links work on sing-box.** sing-box used to send `/ws?ed=2048` as an escaped path and servers answered
  404, so these nodes never connected. Conduit now strips `?ed=` for sing-box. It does not turn on sing-box early
  data: in the lab, sing-box's early data lost about half of the responses against both Xray and sing-box
  servers. On the **Xray core**, `?ed=` stays in the path and Xray uses early data (one round trip less).
- **Quiet logs.** The core logs at `warn`. Turn on *Core → Performance → Detailed logs* only to debug;
  per-connection logging costs CPU under load.
- **No sniffing on full-tunnel ports.** Hybrid ports keep sniffing (domain rules need it) with a 50 ms
  timeout, so server-first protocols such as SSH don't wait 300 ms per connection.
- **Cheap monitoring.** The Dashboard counts the core's open sockets from `/proc/<pid>/fd` instead of
  reading the whole TCP table, and stops polling while its tab is hidden.
- **Container limits.** The compose files raise the open-file limit to 1,048,576 and the accept queues to
  65,535, and allow TCP Fast Open.

## Options in the UI

| Option | Where | When to use it |
|---|---|---|
| **Auto (fastest)** | Proxy → Nodes | Several nodes and you want the one with the lowest *real* delay. sing-box `urltest` probes the test URL through each node every minute and switches only when another node is faster by more than 50 ms. Xray uses a `leastPing` balancer. |
| **Multiplex** (per node) | Proxy → Edit node | Many short requests. Reuses up to 4 warm connections to the node instead of a handshake chain per request. **The server must support it** (below). Skipped for XTLS Vision nodes. Can slow large downloads: one lost packet stalls every stream on that connection. |
| **TCP Fast Open** | Core → Performance | Saves a round trip on repeat connections. Needs TFO on this host and the node; some networks drop TFO packets. |

## Server side (your nodes)

### Multiplex
The protocol has to match what you choose for the node in Conduit.

sing-box server, on the inbound:
```json
"multiplex": { "enabled": true }
```
That accepts h2mux, smux and yamux. Optional: `"padding": true` only if you also enable padding on clients.

Xray server: nothing to add for VLESS/VMess (Xray mux is accepted automatically). Any multiplex value other
than *Off* in Conduit turns on Xray mux on Xray cores. A sing-box core cannot multiplex to an Xray server;
use the Xray core in Conduit for those nodes, or leave multiplex off.

### WebSocket early data (Xray core)
Xray servers accept it with no config change; add `?ed=2048` to the path in the share link
(`path=%2Fws%3Fed%3D2048`) and run the node on the Xray core.

### Transport
VLESS + Reality + Vision over plain TCP has no WebSocket upgrade, so it is one round trip faster than WS+TLS
for new connections, and the fastest option for bulk traffic. It cannot be multiplexed.

## Host tuning (Linux)

On the Conduit host and on your nodes:
```bash
cat <<'SYSCTL' | sudo tee /etc/sysctl.d/90-conduit.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.ipv4.tcp_slow_start_after_idle = 0
SYSCTL
sudo sysctl --system
```
BBR keeps queues short under load, which lowers latency when the link is busy, and recovers much faster
than the default on lossy long-distance routes.

**Host networking.** `docker-compose.host.yml` runs Conduit with `network_mode: host`, which takes Docker's
NAT and connection tracking off the proxy path. Use it on a dedicated Linux host; the CONDUIT_* ports must be
free there.

## Benchmark

`bench/bench.py` (Python standard library only) sends requests through an HTTP proxy with CONNECT and reports
p50/p95/p99 time to first byte, per mode:

```bash
python3 bench/bench.py --proxy HOST:8081 --user U --password P --target example.com:443 --tls \
  -n 500 -c 50 --mode new      # a new tunnel per request: the full handshake chain every time
python3 bench/bench.py --proxy HOST:8081 --target example.com:443 --tls -n 2000 -c 50 --mode reuse
```

`bench/convert/run.sh <image>` checks every supported share-link shape end to end on both cores against a real
Xray server (VLESS WS/TCP/gRPC/Reality/httpupgrade/xhttp, VMess, Trojan, Shadowsocks), plus Domains rules
surviving a core switch.

`bench/lab/` is a reproducible lab: Conduit, real Xray and sing-box nodes with an added round-trip delay
(`NODE_DELAY_MS`, default 100) on the Conduit ↔ node leg, and a local target. `bench/lab/run.sh <label>
<image> [--servers xray|sing-box] [--ed] [--multiplex h2mux] [--mode auto]` runs every scenario, including
switching nodes three times under load, and `bench/report.py a.jsonl b.jsonl` compares two runs.
Results from the lab are in `bench/results/`.
