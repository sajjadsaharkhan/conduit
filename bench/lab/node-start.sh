#!/bin/sh
# Delay only what the node sends back to Conduit, so Conduit <-> node RTT is NODE_DELAY_MS while the
# node <-> target leg stays fast (a node far from you, close to the internet).
set -e
tc qdisc add dev eth0 root handle 1: prio
tc qdisc add dev eth0 parent 1:3 handle 30: netem delay "${NODE_DELAY_MS:-100}ms"
tc filter add dev eth0 protocol ip parent 1:0 prio 3 u32 match ip dst 172.28.0.30/32 flowid 1:3
if [ "$NODE_KIND" = xray ]; then exec xray run -c /etc/node-xray.json; fi
exec sing-box run -c /etc/node-singbox.json
