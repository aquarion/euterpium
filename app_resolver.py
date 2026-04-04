# app_resolver.py — Windows Application ID Resolution
# Resolves friendly application names from Windows Application User Model IDs (AUMIDs)
# and executable paths using multiple strategies: windowsapps library, registry, and parsing

import logging
import re
import sys

logger = logging.getLogger(__name__)

try:
    import windowsapps
    WINDOWSAPPS_AVAILABLE = True
    logger.info("windowsapps loaded — enhanced app name resolution enabled")
except ImportError as e:
    WINDOWSAPPS_AVAILABLE = False
    logger.info(f"windowsapps not available ({e}) — falling back to registry search")


def resolve_app_name(app_id: str) -> str:
    """
    Convert an application identifier to a friendly name.
    
    Handles various formats:
    - Executable names (e.g., "spotify.exe")
    - Windows Store AUMIDs (e.g., "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic")
    - Package family names and other identifiers
    
    Args:
        app_id: Application identifier from SMTC or other Windows APIs
        
    Returns:
        Friendly application name, or a cleaned version of the input if resolution fails
    """
    raw = (app_id or "unknown").strip()
    if not raw:
        return "unknown"

    lowered = raw.lower()
    
    # Check for executable names first (fastest path)
    exe_match = re.search(r"([a-z0-9_-]+\.exe)", lowered)
    if exe_match:
        return exe_match.group(1)

    # Try advanced resolution for complex identifiers
    resolved = _resolve_app_name_from_aumid(raw)
    if resolved:
        return resolved.lower()

    # Fallback: clean up the identifier
    cleaned = lowered.replace("!", ".")
    parts = [p for p in cleaned.split(".") if p]
    return parts[-1] if parts else lowered


def _resolve_app_name_from_aumid(app_id: str) -> str | None:
    """
    Resolve a friendly app name from an Application User Model ID (AUMID).
    First tries windowsapps package, falls back to registry search if needed.
    
    Args:
        app_id: Windows Application User Model ID
        
    Returns:
        Friendly application name, or None if resolution fails
    """
    if sys.platform != "win32":
        return None

    # Try windowsapps first for better UWP app support
    if WINDOWSAPPS_AVAILABLE:
        try:
            # Try direct lookup by app ID
            result = windowsapps.find_app_by_id(app_id)
            if result != "Application not found!":
                app_name, found_app_id = result
                logger.debug(f"windowsapps: resolved '{app_id}' to '{app_name}'")
                return app_name.strip()
            
            # For partial matches, get all apps and search manually
            apps = windowsapps.get_apps()
            app_id_lower = app_id.lower()
            
            # Try exact match first
            for name, aid in apps.items():
                if aid.lower() == app_id_lower:
                    logger.debug(f"windowsapps: exact match '{app_id}' to '{name}'")
                    return name.strip()
            
            # Try partial matches for package family names in AUMID
            for name, aid in apps.items():
                if app_id_lower in aid.lower() or aid.lower() in app_id_lower:
                    logger.debug(f"windowsapps: partial match '{app_id}' to '{name}' (aid: {aid})")
                    return name.strip()
                    
            logger.debug(f"windowsapps: no match found for AUMID '{app_id}'")
        except Exception as e:
            logger.debug(f"windowsapps lookup failed for '{app_id}': {e}")

    # Fallback to registry search
    return _resolve_from_registry(app_id)


def _resolve_from_registry(app_id: str) -> str | None:
    """
    Fallback resolution using Windows registry lookup.
    
    Args:
        app_id: Application User Model ID
        
    Returns:
        Application name from registry, or None if not found
    """
    try:
        import winreg
    except ImportError:
        return None

    key_paths = [
        (winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{app_id}"),
        (winreg.HKEY_CLASSES_ROOT, rf"AppUserModelId\{app_id}"),
    ]

    value_names = ["RelaunchCommand", "ApplicationName", "DisplayName"]
    for hive, key_path in key_paths:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for value_name in value_names:
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue

                    if not value:
                        continue

                    value_str = str(value).strip()
                    exe_match = re.search(r"([a-z0-9_-]+\.exe)", value_str.lower())
                    if exe_match:
                        return exe_match.group(1)

                    if value_name in {"ApplicationName", "DisplayName"}:
                        return value_str
        except OSError:
            continue

    return None


def is_windowsapps_available() -> bool:
    """Check if the windowsapps library is available for enhanced resolution."""
    return WINDOWSAPPS_AVAILABLE