"""Thread-safe config file operations with caching and atomic writes."""
import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigFileManager:
    """Thread-safe config file operations with caching."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_mtime: Optional[float] = None

    def read_config(self) -> Dict[str, Any]:
        """Read config from file with caching."""
        with self._lock:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Config file not found: {self.config_path}")

            current_mtime = self.config_path.stat().st_mtime
            if self._cache and self._cache_mtime == current_mtime:
                return self._cache.copy()  # Return a copy to prevent external modifications

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self._cache = config
                self._cache_mtime = current_mtime
                return config.copy()

    def write_config(self, config: Dict[str, Any]) -> None:
        """Write config to file atomically."""
        with self._lock:
            # Ensure parent directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first, then rename (atomic operation)
            temp_path = self.config_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.config_path)

            # Update cache
            self._cache = config
            self._cache_mtime = self.config_path.stat().st_mtime

    def update_section(self, section: str, data: Any) -> Dict[str, Any]:
        """Update a specific section of the config."""
        config = self.read_config()
        config[section] = data
        self.write_config(config)
        return config

    def get_section(self, section: str) -> Any:
        """Get a specific section from the config."""
        config = self.read_config()
        if section not in config:
            raise KeyError(f"Section '{section}' not found in config")
        return config[section]

    def invalidate_cache(self) -> None:
        """Invalidate the config cache."""
        with self._lock:
            self._cache = None
            self._cache_mtime = None

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_path.exists()

    def ensure_exists(self, default_config: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure config file exists, create with default if not."""
        if not self.exists():
            self.write_config(default_config)
            return default_config.copy()
        return self.read_config()
