"""Start/stop core process (sing-box or Xray) with generated config; capture stdout and stderr for logs."""
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

CONFIG_PATH = os.environ.get("SINGBOX_CONFIG_PATH", "/data/singbox_config.json")
XRAY_CONFIG_PATH = os.environ.get("XRAY_CONFIG_PATH", "/data/xray_config.json")
SINGBOX_BIN = os.environ.get("SINGBOX_BIN", "sing-box")
XRAY_BIN = os.environ.get("XRAY_BIN", "xray")
MAX_LOG_LINES = 2000

_process: Optional["subprocess.Popen"] = None
_started_at: Optional[float] = None  # Unix timestamp when process was started (for uptime)
_log_buffer: deque = deque(maxlen=MAX_LOG_LINES)
_reader_threads: list = []


def get_config_path() -> str:
    p = Path(CONFIG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def get_xray_config_path() -> str:
    p = Path(XRAY_CONFIG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _read_stream(stream) -> None:
    """Background thread: read stream (stdout or stderr) line by line into _log_buffer."""
    global _log_buffer
    try:
        for line in iter(stream.readline, b""):
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    _log_buffer.append(text)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def is_running() -> bool:
    global _process
    return _process is not None and _process.poll() is None


def start(config_path: Optional[str] = None, core_type: str = "sing-box") -> bool:
    """Start core (sing-box or xray) with config. Returns True if started. Captures stdout and stderr to log buffer."""
    global _process, _started_at, _log_buffer, _reader_threads
    stop()
    path = config_path or (get_xray_config_path() if core_type == "xray" else get_config_path())
    if not Path(path).exists():
        return False
    try:
        if core_type == "xray":
            cmd = [XRAY_BIN, "run", "-c", path]
        else:
            cmd = [SINGBOX_BIN, "run", "-c", path]
        _process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        _started_at = time.time()
        _log_buffer.clear()
        _reader_threads = []
        if _process.stdout:
            t = threading.Thread(target=_read_stream, args=(_process.stdout,), daemon=True)
            t.start()
            _reader_threads.append(t)
        if _process.stderr:
            t = threading.Thread(target=_read_stream, args=(_process.stderr,), daemon=True)
            t.start()
            _reader_threads.append(t)
        return _process.poll() is None
    except FileNotFoundError:
        _started_at = None
        return False
    except Exception:
        _started_at = None
        return False


def stop() -> None:
    """Stop core process."""
    global _process, _started_at, _reader_threads
    _started_at = None
    if _process is not None:
        try:
            _process.terminate()
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
        except Exception:
            pass
        _process = None
    _reader_threads = []


def restart(config_path: Optional[str] = None, core_type: str = "sing-box") -> bool:
    """Stop then start. Returns True if start succeeded."""
    stop()
    return start(config_path, core_type)


def status() -> dict:
    """Return status dict: running (bool), pid (optional), started_at (optional unix timestamp for uptime)."""
    global _process, _started_at
    if _process is not None and _process.poll() is None:
        return {"running": True, "pid": _process.pid, "started_at": _started_at}
    return {"running": False, "pid": None, "started_at": None}


def get_logs(tail: int = 500) -> list:
    """Return last `tail` log lines (newest last)."""
    global _log_buffer
    lines = list(_log_buffer)
    if len(lines) <= tail:
        return lines
    return lines[-tail:]
