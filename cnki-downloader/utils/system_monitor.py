"""System resource monitoring (CPU, memory, disk)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class SystemStats:
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_rss_mb: float = 0.0
    memory_percent: float = 0.0
    disk_free_gb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_rss_mb": round(self.memory_rss_mb, 1),
            "memory_percent": round(self.memory_percent, 1),
            "disk_free_gb": round(self.disk_free_gb, 2),
        }


def get_system_stats(storage_path: Optional[str] = None) -> SystemStats:
    """Collect current system resource usage."""
    stats = SystemStats()

    if HAS_PSUTIL:
        process = psutil.Process(os.getpid())
        stats.cpu_percent = process.cpu_percent(interval=0.1)
        mem = process.memory_info()
        stats.memory_rss_mb = mem.rss / (1024 * 1024)
        stats.memory_percent = process.memory_percent()

        if storage_path:
            try:
                usage = psutil.disk_usage(storage_path)
                stats.disk_free_gb = usage.free / (1024 ** 3)
            except Exception:
                pass

    return stats


def check_disk_available(path: str, min_free_gb: float = 1.0) -> bool:
    """Check if enough disk space is available."""
    try:
        usage = psutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= min_free_gb
    except Exception:
        return True
