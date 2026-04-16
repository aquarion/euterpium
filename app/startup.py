# startup.py — Windows startup registry helpers
#
# Manages the HKCU\Software\Microsoft\Windows\CurrentVersion\Run entry
# so Euterpium can optionally launch when Windows starts.
# No-ops silently on non-Windows platforms.
#
# Note: this is only meaningful when running as a PyInstaller bundle —
# sys.executable points to the .exe in that case. When running from source
# (poetry run python main.py) it points to the Python interpreter, which
# would not start the app correctly. The UI hides the option on non-win32.

import logging
import sys

from version import APP_DISPLAY_NAME

logger = logging.getLogger(__name__)

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_VALUE = APP_DISPLAY_NAME


def _exe_path() -> str:
    """Return the path to register — quoted to handle spaces."""
    return f'"{sys.executable}"'


def _parse_exe_path(value: str) -> str:
    """Strip wrapping quotes from a registry value for comparison."""
    return value.strip('"')


def is_enabled() -> bool:
    """Return True if the startup registry entry exists and points to our exe."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _REG_VALUE)
            return _parse_exe_path(value).lower() == sys.executable.lower()
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
