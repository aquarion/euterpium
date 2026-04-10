# tests/conftest.py — shared fixtures

import os
import sys

import pytest

# Ensure the project root is on sys.path so modules resolve without installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as _config_module


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """
    Redirects all config reads/writes to a fresh temp file.
    Prevents tests from touching the real user config.
    """
    cfg_file = tmp_path / "euterpium.ini"
    monkeypatch.setattr(_config_module, "_CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(_config_module, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(_config_module, "_CONFIG_UNAVAILABLE", False)
    return cfg_file
