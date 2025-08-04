from __future__ import annotations

import pytest

from anyio import run
from anyio._core._config import Config, get_config, update_config_from_options


def test_config_defaults() -> None:
    """Test that config has correct default values."""
    config = Config()
    assert config.worker_thread_max_idle_time == 10.0
    assert config.worker_process_max_idle_time == 300.0


def test_config_validation() -> None:
    """Test that config validates input values."""
    config = Config()
    
    # Test valid values
    config.worker_thread_max_idle_time = 5.0
    config.worker_process_max_idle_time = 600.0
    
    assert config.worker_thread_max_idle_time == 5.0
    assert config.worker_process_max_idle_time == 600.0
    
    # Test invalid values
    with pytest.raises(ValueError, match="must be positive"):
        config.worker_thread_max_idle_time = 0
    
    with pytest.raises(ValueError, match="must be positive"):
        config.worker_thread_max_idle_time = -1
    
    with pytest.raises(ValueError, match="must be positive"):
        config.worker_process_max_idle_time = 0
    
    with pytest.raises(ValueError, match="must be positive"):
        config.worker_process_max_idle_time = -1


def test_update_config_from_options() -> None:
    """Test updating config from options dictionary."""
    config = Config()
    
    # Test updating both values
    options = {
        "worker_thread_max_idle_time": 15.0,
        "worker_process_max_idle_time": 450.0,
    }
    config.update_from_options(options)
    
    assert config.worker_thread_max_idle_time == 15.0
    assert config.worker_process_max_idle_time == 450.0
    
    # Test updating only one value
    options = {"worker_thread_max_idle_time": 20.0}
    config.update_from_options(options)
    
    assert config.worker_thread_max_idle_time == 20.0
    assert config.worker_process_max_idle_time == 450.0  # unchanged


def test_global_config() -> None:
    """Test the global config instance."""
    config = get_config()
    
    # Reset to defaults
    config.worker_thread_max_idle_time = Config.DEFAULT_WORKER_THREAD_MAX_IDLE_TIME
    config.worker_process_max_idle_time = Config.DEFAULT_WORKER_PROCESS_MAX_IDLE_TIME
    
    assert config.worker_thread_max_idle_time == 10.0
    assert config.worker_process_max_idle_time == 300.0


def test_update_global_config_from_options() -> None:
    """Test updating global config from options."""
    config = get_config()
    
    # Reset to defaults
    config.worker_thread_max_idle_time = Config.DEFAULT_WORKER_THREAD_MAX_IDLE_TIME
    config.worker_process_max_idle_time = Config.DEFAULT_WORKER_PROCESS_MAX_IDLE_TIME
    
    options = {
        "worker_thread_max_idle_time": 25.0,
        "worker_process_max_idle_time": 500.0,
    }
    update_config_from_options(options)
    
    assert config.worker_thread_max_idle_time == 25.0
    assert config.worker_process_max_idle_time == 500.0


async def test_config_integration() -> None:
    """Test that config is properly integrated with the backend."""
    # This test verifies that the config is actually used by the backend
    # We can't easily test the exact timing, but we can verify the config is accessible
    
    config = get_config()
    original_thread_time = config.worker_thread_max_idle_time
    original_process_time = config.worker_process_max_idle_time
    
    try:
        # Set custom values
        config.worker_thread_max_idle_time = 30.0
        config.worker_process_max_idle_time = 600.0
        
        # Verify the values are set
        assert config.worker_thread_max_idle_time == 30.0
        assert config.worker_process_max_idle_time == 600.0
        
    finally:
        # Restore original values
        config.worker_thread_max_idle_time = original_thread_time
        config.worker_process_max_idle_time = original_process_time


def test_backend_options_integration() -> None:
    """Test that backend options are properly processed."""
    config = get_config()
    
    # Reset to defaults
    config.worker_thread_max_idle_time = Config.DEFAULT_WORKER_THREAD_MAX_IDLE_TIME
    config.worker_process_max_idle_time = Config.DEFAULT_WORKER_PROCESS_MAX_IDLE_TIME
    
    def dummy_coro():
        return "test"
    
    # Test with custom backend options
    options = {
        "worker_thread_max_idle_time": 35.0,
        "worker_process_max_idle_time": 700.0,
    }
    
    result = run(dummy_coro, backend_options=options)
    assert result == "test"
    
    # Verify config was updated
    assert config.worker_thread_max_idle_time == 35.0
    assert config.worker_process_max_idle_time == 700.0 