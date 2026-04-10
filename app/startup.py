# startup.py — Windows startup registry helpers
#
# Manages the HKCU\Software\Microsoft\Windows\CurrentVersion\Run entry
# so Euterpium can optionally launch when Windows starts.
# No-ops silently on non-Windows platforms.

import logging
import sys

logger = logging.getLogger(__name__)

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_VALUE = "Euterpium"


def _exe_path() -> str:
    """Return the path to register — the running executable."""
    return sys.executable


def is_enabled() -> bool:
    """Return True if the startup registry entry exists and points to our exe."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _REG_VALUE)
            return value == _exe_path()
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning("Could not read startup registry entry: %s", e)
        return False


def enable() -> bool:
    """Write the startup registry entry. Returns True on success."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _REG_VALUE, 0, winreg.REG_SZ, _exe_path())
        logger.info("Launch on startup enabled (%s)", _exe_path())
        return True
    except Exception as e:
        logger.warning("Could not write startup registry entry: %s", e)
        return False


def disable() -> bool:
    """Remove the startup registry entry if present. Returns True on success."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _REG_VALUE)
        logger.info("Launch on startup disabled")
        return True
    except FileNotFoundError:
        return True  # already absent — treat as success
    except Exception as e:
        logger.warning("Could not remove startup registry entry: %s", e)
        return False
