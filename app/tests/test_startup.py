# tests/test_startup.py — startup registry helpers
#
# winreg is imported lazily inside each function, so we can mock it via
# sys.modules on all platforms without a pytestmark skip.

import sys
from unittest.mock import MagicMock, patch

import pytest

import startup


@pytest.fixture
def mock_winreg():
    """Provide a mock winreg module injected into sys.modules."""
    winreg = MagicMock()
    winreg.HKEY_CURRENT_USER = "HKCU"
    winreg.KEY_SET_VALUE = 0x0002
    winreg.REG_SZ = 1
    # OpenKey returns a context manager
    winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=winreg.OpenKey.return_value)
    winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
    with patch.dict(sys.modules, {"winreg": winreg}):
        yield winreg


# ── non-Windows no-ops ────────────────────────────────────────────────────────


def test_is_enabled_returns_false_on_non_windows():
    with patch.object(startup.sys, "platform", "linux"):
        assert startup.is_enabled() is False


def test_enable_returns_false_on_non_windows():
    with patch.object(startup.sys, "platform", "linux"):
        assert startup.enable() is False


def test_disable_returns_false_on_non_windows():
    with patch.object(startup.sys, "platform", "linux"):
        assert startup.disable() is False


# ── is_enabled ────────────────────────────────────────────────────────────────


def test_is_enabled_returns_true_when_key_matches_exe(mock_winreg):
    exe = startup._exe_path()
    mock_winreg.QueryValueEx.return_value = (exe, mock_winreg.REG_SZ)

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.is_enabled()

    assert result is True
    mock_winreg.OpenKey.assert_called_once_with(mock_winreg.HKEY_CURRENT_USER, startup._REG_KEY)


def test_is_enabled_returns_false_when_key_points_to_different_exe(mock_winreg):
    mock_winreg.QueryValueEx.return_value = ("C:\\other\\app.exe", mock_winreg.REG_SZ)

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.is_enabled()

    assert result is False


def test_is_enabled_returns_false_when_key_absent(mock_winreg):
    mock_winreg.OpenKey.side_effect = FileNotFoundError

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.is_enabled()

    assert result is False


def test_is_enabled_returns_false_on_exception(mock_winreg):
    mock_winreg.OpenKey.side_effect = OSError("access denied")

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.is_enabled()

    assert result is False


# ── enable ────────────────────────────────────────────────────────────────────


def test_enable_writes_registry_entry(mock_winreg):
    with patch.object(startup.sys, "platform", "win32"):
        result = startup.enable()

    assert result is True
    mock_winreg.SetValueEx.assert_called_once_with(
        mock_winreg.OpenKey.return_value,
        startup._REG_VALUE,
        0,
        mock_winreg.REG_SZ,
        startup._exe_path(),
    )


def test_enable_opens_key_with_write_access(mock_winreg):
    with patch.object(startup.sys, "platform", "win32"):
        startup.enable()

    mock_winreg.OpenKey.assert_called_once_with(
        mock_winreg.HKEY_CURRENT_USER,
        startup._REG_KEY,
        access=mock_winreg.KEY_SET_VALUE,
    )


def test_enable_returns_false_on_exception(mock_winreg):
    mock_winreg.OpenKey.side_effect = OSError("access denied")

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.enable()

    assert result is False


# ── disable ───────────────────────────────────────────────────────────────────


def test_disable_removes_registry_entry(mock_winreg):
    with patch.object(startup.sys, "platform", "win32"):
        result = startup.disable()

    assert result is True
    mock_winreg.DeleteValue.assert_called_once_with(
        mock_winreg.OpenKey.return_value, startup._REG_VALUE
    )


def test_disable_returns_true_when_key_already_absent(mock_winreg):
    mock_winreg.OpenKey.side_effect = FileNotFoundError

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.disable()

    assert result is True


def test_disable_returns_true_when_value_already_absent(mock_winreg):
    mock_winreg.DeleteValue.side_effect = FileNotFoundError

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.disable()

    assert result is True


def test_disable_returns_false_on_exception(mock_winreg):
    mock_winreg.OpenKey.side_effect = OSError("access denied")

    with patch.object(startup.sys, "platform", "win32"):
        result = startup.disable()

    assert result is False
