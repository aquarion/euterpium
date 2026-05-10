# config.py — reads settings from the platform-appropriate user config directory
#
# Config file location:
#   Windows : %LOCALAPPDATA%\euterpium\euterpium.ini
#   Linux   : ~/.config/euterpium/euterpium.ini
#   macOS   : ~/.config/euterpium/euterpium.ini
#
# On first run, the bundled euterpium.ini (next to this file) is copied there
# as a starting point if no user config exists yet.

import configparser
import logging
import os
import shutil

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

APP_NAME = "euterpium"
CONFIG_FILE = "euterpium.ini"

# Bundled defaults (lives next to this source file)
_BUNDLED_DEFAULTS = os.path.join(os.path.dirname(__file__), CONFIG_FILE)

# User config path
_CONFIG_DIR = user_config_dir(APP_NAME, appauthor=False)
_CONFIG_PATH = os.path.join(_CONFIG_DIR, CONFIG_FILE)

# Flag set if the config directory/file is not accessible
_CONFIG_UNAVAILABLE = False


def config_path() -> str:
    """Returns the active config file path (for display in the UI)."""
    return _CONFIG_PATH


def _ensure_config():
    """Creates the user config dir and seeds it from bundled defaults if needed."""
    global _CONFIG_UNAVAILABLE
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        if not os.path.exists(_CONFIG_PATH):
            if os.path.exists(_BUNDLED_DEFAULTS):
                shutil.copy2(_BUNDLED_DEFAULTS, _CONFIG_PATH)
                logger.info(f"Created config at {_CONFIG_PATH}")
            else:
                open(_CONFIG_PATH, "w").close()
                logger.warning("No bundled euterpium.ini found — created empty config")
    except OSError as e:
        logger.error(
            f"Cannot create config directory {_CONFIG_DIR}: {e} — running with defaults only"
        )
        _CONFIG_UNAVAILABLE = True


# Ensure config exists at import time
_ensure_config()


def _load() -> configparser.ConfigParser:
    """
    Loads the config file. Returns an empty (defaults-only) parser if the file
    is missing, unreadable, or contains syntax errors.
    """
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    if _CONFIG_UNAVAILABLE:
        return cfg
    try:
        cfg.read(_CONFIG_PATH, encoding="utf-8")
    except (configparser.Error, OSError) as e:
        logger.error(f"Failed to read config file ({e}) — using built-in defaults")
    return cfg


def _cfg() -> configparser.ConfigParser:
    """Returns a freshly loaded config (so changes on disk are always reflected)."""
    return _load()


def _getint(cfg: configparser.ConfigParser, section: str, key: str, fallback: int) -> int:
    """getint with a fallback on ValueError (e.g. non-numeric value in file)."""
    try:
        return cfg.getint(section, key, fallback=fallback)
    except (ValueError, configparser.Error):
        logger.warning(f"Invalid value for [{section}] {key} — using default ({fallback})")
        return fallback


def _getfloat(cfg: configparser.ConfigParser, section: str, key: str, fallback: float) -> float:
    """getfloat with a fallback on ValueError."""
    try:
        return cfg.getfloat(section, key, fallback=fallback)
    except (ValueError, configparser.Error):
        logger.warning(f"Invalid value for [{section}] {key} — using default ({fallback})")
        return fallback


def _getbool(cfg: configparser.ConfigParser, section: str, key: str, fallback: bool) -> bool:
    """Parse a config value as a boolean, using fallback silently when absent."""
    try:
        return cfg.getboolean(section, key, fallback=fallback)
    except (ValueError, configparser.Error):
        raw = cfg.get(section, key, fallback=None)
        logger.warning(f"Invalid value for [{section}] {key}: {raw!r} — using default ({fallback})")
        return fallback


# ── Logging ───────────────────────────────────────────────────────────────────


def get_log_level() -> int:
    """Returns the configured logging level (default: INFO)."""
    raw = _cfg().get("logging", "level", fallback="INFO").strip().upper()
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        logger.warning("Invalid log level %r in config — using INFO", raw)
        return logging.INFO
    return level


# ── Configured checks ────────────────────────────────────────────────────────

_PLACEHOLDER_URLS = {"", "https://your-api.com/now-playing"}


def acrcloud_is_configured() -> bool:
    """True if both ACRCloud key and secret are non-empty."""
    return bool(get_acrcloud_access_key() and get_acrcloud_access_secret())


def api_is_configured() -> bool:
    """True if the API URL has been set to something other than the placeholder."""
    return get_api_url() not in _PLACEHOLDER_URLS


def is_configured() -> bool:
    """True if the minimum required credentials are present to do useful work."""
    return acrcloud_is_configured() and api_is_configured()


# ── ACRCloud ──────────────────────────────────────────────────────────────────


def get_acrcloud_host() -> str:
    return _cfg().get("acrcloud", "host", fallback="identify-eu-west-1.acrcloud.com")


def get_acrcloud_access_key() -> str:
    return _cfg().get("acrcloud", "access_key", fallback="")


def get_acrcloud_access_secret() -> str:
    return _cfg().get("acrcloud", "access_secret", fallback="")


def get_acrcloud_language() -> str:
    """Returns the preferred language code for ACRCloud results.

    Priority: [acrcloud] language in INI → Windows locale → 'en'.
    """
    explicit = _cfg().get("acrcloud", "language", fallback="").strip()
    if explicit:
        return explicit
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as key:
            value, _ = winreg.QueryValueEx(key, "LocaleName")
            if not isinstance(value, str):
                return "en"
            stripped = value.strip()
            return stripped if stripped else "en"
    except (ImportError, OSError):
        return "en"


# ── Your API ──────────────────────────────────────────────────────────────────


def get_active_profile() -> str:
    return _cfg().get("api", "active", fallback="")


def get_api_profiles() -> dict[str, dict[str, str]]:
    """Returns {profile_name: {url, key}} for all [api:*] sections."""
    cfg = _cfg()
    profiles = {}
    for section in cfg.sections():
        if section.startswith("api:"):
            name = section[4:]
            profiles[name] = {
                "url": cfg.get(section, "url", fallback=""),
                "key": cfg.get(section, "key", fallback=""),
            }
    return profiles


def get_api_url(profile: str | None = None) -> str:
    if profile is None:
        profile = get_active_profile()
    cfg = _cfg()
    section = f"api:{profile}"
    if cfg.has_section(section):
        return cfg.get(section, "url", fallback="")
    # Legacy fallback: single [api] url
    return cfg.get("api", "url", fallback="")


def get_api_key(profile: str | None = None) -> str:
    if profile is None:
        profile = get_active_profile()
    cfg = _cfg()
    section = f"api:{profile}"
    if cfg.has_section(section):
        return cfg.get(section, "key", fallback="")
    # Legacy fallback: single [api] key
    return cfg.get("api", "key", fallback="")


# ── Audio ─────────────────────────────────────────────────────────────────────


def get_sample_rate() -> int:
    return _getint(_cfg(), "audio", "sample_rate", 44100)


def get_capture_seconds() -> float:
    return _getfloat(_cfg(), "audio", "capture_seconds", 10.0)


def get_poll_interval() -> float:
    return _getfloat(_cfg(), "audio", "poll_interval", 1.0)


def get_min_silence_before_change() -> int:
    return _getint(_cfg(), "audio", "min_silence_before_change", 2)


def get_min_rms() -> float:
    return _getfloat(_cfg(), "audio", "min_rms", 0.01)


def get_spectral_flatness_threshold() -> float:
    return _getfloat(_cfg(), "audio", "spectral_flatness_threshold", 0.6)


def get_fingerprint_bands() -> int:
    return max(1, _getint(_cfg(), "audio", "fingerprint_bands", 32))


def get_fingerprint_change_threshold() -> float:
    return _getfloat(_cfg(), "audio", "fingerprint_change_threshold", 0.35)


# ── Games ─────────────────────────────────────────────────────────────────────


def get_known_games() -> dict[str, str]:
    """Returns {process_name: display_name} from the [games] section."""
    cfg = _cfg()
    if not cfg.has_section("games"):
        return {}
    return dict(cfg.items("games"))


def get_playnite_current_game_path() -> str:
    """Returns the path to the file the Playnite plugin writes when a game is running."""
    raw = _cfg().get("playnite", "current_game_file", fallback="").strip()
    if raw:
        return raw
    return os.path.join(os.environ.get("APPDATA", ""), "Playnite", "euterpium_current_game.json")


# ── SMTC ──────────────────────────────────────────────────────────────────────


def get_smtc_ignored_apps() -> list[str]:
    """
    Returns a list of lowercase substrings. Any SMTC session whose
    source_app_user_model_id contains one of these is ignored.
    """
    raw = _cfg().get("smtc", "ignore", fallback="chrome.exe,firefox.exe")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


# ── General / UI ─────────────────────────────────────────────────────────────


def get_start_minimised() -> bool:
    return _getbool(_cfg(), "general", "start_minimised", False)


# ── REST API ──────────────────────────────────────────────────────────────────


def get_rest_api_enabled() -> bool:
    return _getbool(_cfg(), "rest_api", "enabled", True)


def get_rest_api_port() -> int:
    port = _getint(_cfg(), "rest_api", "port", 43174)
    if port < 1024 or port > 65535:
        logger.warning("REST API port %d is out of range (1024–65535) — using default 43174", port)
        return 43174
    return port


def get_rest_api_key() -> str:
    """Return the REST API bearer token, generating and persisting one if absent.

    If the config directory is unavailable, returns an ephemeral per-run key so auth
    is always enforced. The Playnite plugin will not be able to connect in that session
    (it also reads the key from the same config file).
    """
    import secrets

    key = _cfg().get("rest_api", "key", fallback="").strip()
    if key:
        return key
    if _CONFIG_UNAVAILABLE:
        ephemeral = secrets.token_urlsafe(32)
        logger.warning(
            "Config unavailable — REST API will use an ephemeral key for this run; "
            "Playnite plugin integration will not work until config is accessible"
        )
        return ephemeral
    new_key = secrets.token_urlsafe(32)
    save({"rest_api": {"key": new_key}})
    logger.info("Generated REST API bearer token and saved to config")
    return new_key


# ── Write helper ──────────────────────────────────────────────────────────────


def save(updates: dict[str, dict[str, str]]) -> bool:
    """
    Merges updates into the user config file and saves.
    Returns True on success, False if the file could not be written.

    updates = {
        "acrcloud": {"access_key": "...", "access_secret": "..."},
        "api": {"url": "...", "key": "..."},
        ...
    }
    """
    if _CONFIG_UNAVAILABLE:
        logger.error("Config directory unavailable — settings cannot be saved")
        return False

    cfg = _load()
    for section, values in updates.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for key, value in values.items():
            cfg.set(section, key, value)

    # Write to a temp file then rename, so a failed write doesn't corrupt the existing config
    tmp_path = _CONFIG_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            cfg.write(f)
        os.replace(tmp_path, _CONFIG_PATH)
        logger.debug(f"Config saved to {_CONFIG_PATH}")
        return True
    except OSError as e:
        logger.error(f"Failed to save config: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def _migrate_legacy_api():
    """
    Migrates a single-endpoint [api] url/key config to [api:dev] on first load.
    Leaves the file unchanged if [api:*] sections already exist.
    """
    cfg = _load()
    has_profiles = any(s.startswith("api:") for s in cfg.sections())
    if has_profiles:
        return
    legacy_url = cfg.get("api", "url", fallback="")
    legacy_key = cfg.get("api", "key", fallback="")
    if not legacy_url or legacy_url in _PLACEHOLDER_URLS:
        return
    logger.info("Migrating legacy [api] url/key to [api:dev]")
    save(
        {
            "api": {"active": "dev"},
            "api:dev": {"url": legacy_url, "key": legacy_key},
        }
    )


_migrate_legacy_api()


# ── Convenience constants (evaluated at import time) ──────────────────────────
# Use the get_* functions above if you need live values after a settings save.

ACRCLOUD_HOST = get_acrcloud_host()
ACRCLOUD_ACCESS_KEY = get_acrcloud_access_key()
ACRCLOUD_ACCESS_SECRET = get_acrcloud_access_secret()

YOUR_API_URL = get_api_url()
YOUR_API_KEY = get_api_key()
ACTIVE_PROFILE = get_active_profile()

SAMPLE_RATE = get_sample_rate()
CAPTURE_SECONDS = get_capture_seconds()
POLL_INTERVAL = get_poll_interval()
MIN_SILENCE_BEFORE_CHANGE = get_min_silence_before_change()

KNOWN_GAMES = get_known_games()
