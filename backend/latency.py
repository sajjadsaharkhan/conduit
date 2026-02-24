"""Latency check for proxy nodes (TCP connect time)."""
import asyncio
import time
from typing import Dict, Any, List, Optional

# Default test: TCP connect to server:port (no proxy used for this check)
TEST_TIMEOUT = 5.0


async def tcp_connect_latency(host: str, port: int, timeout: float = TEST_TIMEOUT) -> Optional[int]:
    """Return round-trip connect latency in ms, or None on failure."""
    try:
        start = time.perf_counter()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
        return int((time.perf_counter() - start) * 1000)
    except Exception:
        return None


def get_server_from_node(node: Dict[str, Any]) -> Optional[tuple]:
    """Extract (host, port) from parsed node dict."""
    if isinstance(node, dict):
        server = node.get("server") or node.get("add")
        port = node.get("server_port") or node.get("port")
        if server and port is not None:
            return (str(server), int(port))
    return None


async def check_node_latency(node: Dict[str, Any], timeout: float = TEST_TIMEOUT) -> Optional[int]:
    """Return latency in ms for one node."""
    addr = get_server_from_node(node)
    if not addr:
        return None
    return await tcp_connect_latency(addr[0], addr[1], timeout=timeout)


async def check_nodes_latency(nodes: List[Dict[str, Any]], timeout: float = TEST_TIMEOUT) -> List[Dict[str, Any]]:
    """
    Check latency for each node in parallel. Mutates nodes in place adding 'latency_ms'.
    Returns same list with latency_ms set (or None if failed).
    """
    async def one(n: Dict[str, Any]) -> None:
        n["latency_ms"] = await check_node_latency(n, timeout)

    await asyncio.gather(*[one(n) for n in nodes])
    return nodes


def select_best_node(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return node with lowest latency_ms (excluding None)."""
    with_latency = [n for n in nodes if n.get("latency_ms") is not None]
    if not with_latency:
        return nodes[0] if nodes else None
    return min(with_latency, key=lambda n: n["latency_ms"])
