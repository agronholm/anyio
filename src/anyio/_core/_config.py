from __future__ import annotations

from typing import Any


class Config:
    """Global configuration for anyio."""

    # Default values
    DEFAULT_WORKER_THREAD_MAX_IDLE_TIME = 10.0  # seconds
    DEFAULT_WORKER_PROCESS_MAX_IDLE_TIME = 300.0  # seconds

    def __init__(self):
        self._worker_thread_max_idle_time = self.DEFAULT_WORKER_THREAD_MAX_IDLE_TIME
        self._worker_process_max_idle_time = self.DEFAULT_WORKER_PROCESS_MAX_IDLE_TIME

    @property
    def worker_thread_max_idle_time(self) -> float:
        """Maximum idle time for worker threads in seconds."""
        return self._worker_thread_max_idle_time

    @worker_thread_max_idle_time.setter
    def worker_thread_max_idle_time(self, value: float) -> None:
        if value <= 0:
            raise ValueError("worker_thread_max_idle_time must be positive")
        self._worker_thread_max_idle_time = value

    @property
    def worker_process_max_idle_time(self) -> float:
        """Maximum idle time for worker processes in seconds."""
        return self._worker_process_max_idle_time

    @worker_process_max_idle_time.setter
    def worker_process_max_idle_time(self, value: float) -> None:
        if value <= 0:
            raise ValueError("worker_process_max_idle_time must be positive")
        self._worker_process_max_idle_time = value

    def update_from_options(self, options: dict[str, Any]) -> None:
        """Update configuration from backend options."""
        if "worker_thread_max_idle_time" in options:
            self.worker_thread_max_idle_time = options["worker_thread_max_idle_time"]
        if "worker_process_max_idle_time" in options:
            self.worker_process_max_idle_time = options["worker_process_max_idle_time"]


# Global configuration instance
_config = Config()


def get_config() -> Config:
    """Get the global configuration instance."""
    return _config


def update_config_from_options(options: dict[str, Any]) -> None:
    """Update global configuration from backend options."""
    _config.update_from_options(options)
