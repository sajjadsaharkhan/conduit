"""URL helpers (e.g. extract host for domain list)."""
from urllib.parse import urlparse


def host_from_url(url: str) -> str | None:
    """Extract hostname from a URL (e.g. https://www.gstatic.com/path -> www.gstatic.com). Returns None if invalid."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.path or "").strip()
        if host and "/" not in host:
            return host
        return host.split("/")[0] if host else None
    except Exception:
        return None
