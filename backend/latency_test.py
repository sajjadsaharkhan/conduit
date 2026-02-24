"""Real latency and download speed test via the local proxy (HTTP)."""
import time
from typing import Any
from urllib.parse import quote

import httpx

# Default proxy port (fixed)
HTTP_PROXY_PORT = 8080
TEST_TIMEOUT = 30.0


def run_latency_test(
    url: str,
    proxy_port: int = HTTP_PROXY_PORT,
    proxy_username: str = "",
    proxy_password: str = "",
) -> dict[str, Any]:
    """
    Download the given URL via the local HTTP proxy and measure latency and download speed.
    Returns dict with latency_ms (time to first byte), duration_ms (total time),
    download_speed_kbps, size_bytes, success, and optional error.
    When proxy_username and proxy_password are set, uses HTTP Basic auth for the proxy.
    """
    if (proxy_username or "").strip() and proxy_password is not None:
        user = quote((proxy_username or "").strip(), safe="")
        passwd = quote(proxy_password or "", safe="")
        proxy_url = f"http://{user}:{passwd}@127.0.0.1:{proxy_port}"
    else:
        proxy_url = f"http://127.0.0.1:{proxy_port}"
    result: dict[str, Any] = {
        "latency_ms": None,
        "duration_ms": None,
        "download_speed_kbps": None,
        "size_bytes": 0,
        "success": False,
        "error": None,
    }
    if not url or not url.startswith(("http://", "https://")):
        result["error"] = "Invalid URL"
        return result
    start_total = time.perf_counter()
    first_byte_time: float | None = None
    total_bytes = 0
    try:
        with httpx.Client(
            proxy=proxy_url,
            timeout=TEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    if first_byte_time is None:
                        first_byte_time = time.perf_counter()
                    total_bytes += len(chunk)
    except httpx.TimeoutException as e:
        result["error"] = f"Timeout: {e}"
        result["duration_ms"] = int((time.perf_counter() - start_total) * 1000)
        return result
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        result["duration_ms"] = int((time.perf_counter() - start_total) * 1000)
        return result
    except Exception as e:
        result["error"] = str(e) if str(e) else type(e).__name__
        result["duration_ms"] = int((time.perf_counter() - start_total) * 1000)
        return result

    end_total = time.perf_counter()
    duration_sec = end_total - start_total
    result["duration_ms"] = int(duration_sec * 1000)
    result["size_bytes"] = total_bytes
    result["success"] = True
    if first_byte_time is not None:
        result["latency_ms"] = int((first_byte_time - start_total) * 1000)
    else:
        result["latency_ms"] = result["duration_ms"]
    if duration_sec > 0 and total_bytes > 0:
        # kbps = kilobits per second = (bytes * 8) / 1000 / duration_sec
        result["download_speed_kbps"] = round((total_bytes * 8) / 1000 / duration_sec, 2)
    return result
