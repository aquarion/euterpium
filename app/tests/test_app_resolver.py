# tests/test_app_resolver.py — resolve_app_name and resolution strategy coverage

import sys

import app_resolver

# ── resolve_app_name edge cases ───────────────────────────────────────────────


def test_resolve_app_name_whitespace_only_returns_unknown():
    assert app_resolver.resolve_app_name("   ") == "unknown"


def test_resolve_app_name_none_returns_unknown():
    assert app_resolver.resolve_app_name(None) == "unknown"


def test_resolve_app_name_returns_cleaned_fallback_without_exe():
    # No exe match, no windowsapps/registry resolution — falls back to last dot-part
    result = app_resolver.resolve_app_name("com.example.myapp!App")
    assert result == "app"


def test_resolve_app_name_lowercases_resolved_aumid(monkeypatch):
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", False)
    monkeypatch.setattr(sys, "platform", "win32")

    # Inject a fake winreg that returns a display name
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_query(key, name):
        if name == "DisplayName":
            return ("Apple Music", 1)
        raise OSError

    fake_winreg = type(
        "winreg",
        (),
        {
            "HKEY_CURRENT_USER": 0,
            "HKEY_CLASSES_ROOT": 1,
            "OpenKey": staticmethod(lambda hive, path: FakeKey()),
            "QueryValueEx": staticmethod(fake_query),
        },
    )()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    result = app_resolver.resolve_app_name("AppleInc.AppleMusic_8wekyb3d8bbwe!App")
    assert result == "apple music"


# ── is_windowsapps_available ──────────────────────────────────────────────────


def test_is_windowsapps_available_reflects_module_flag(monkeypatch):
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)
    assert app_resolver.is_windowsapps_available() is True

    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", False)
    assert app_resolver.is_windowsapps_available() is False


# ── _resolve_app_name_from_aumid ──────────────────────────────────────────────


def test_resolve_from_aumid_returns_none_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert app_resolver._resolve_app_name_from_aumid("some.app.id") is None


def test_resolve_from_aumid_uses_direct_lookup(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)

    fake_windowsapps = type(
        "windowsapps",
        (),
        {"find_app_by_id": staticmethod(lambda app_id: ("Spotify", "spotify_id"))},
    )()
    monkeypatch.setattr(app_resolver, "windowsapps", fake_windowsapps, raising=False)

    result = app_resolver._resolve_app_name_from_aumid("SpotifyAB.SpotifyMusic_xxx!Spotify")
    assert result == "Spotify"


def test_resolve_from_aumid_falls_back_to_exact_match(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)

    fake_windowsapps = type(
        "windowsapps",
        (),
        {
            "find_app_by_id": staticmethod(lambda app_id: "Application not found!"),
            "get_apps": staticmethod(
                lambda: {"Apple Music": "AppleInc.AppleMusic_8wekyb3d8bbwe!App"}
            ),
        },
    )()
    monkeypatch.setattr(app_resolver, "windowsapps", fake_windowsapps, raising=False)

    result = app_resolver._resolve_app_name_from_aumid("AppleInc.AppleMusic_8wekyb3d8bbwe!App")
    assert result == "Apple Music"


def test_resolve_from_aumid_falls_back_to_partial_match(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)

    fake_windowsapps = type(
        "windowsapps",
        (),
        {
            "find_app_by_id": staticmethod(lambda app_id: "Application not found!"),
            "get_apps": staticmethod(
                lambda: {"Apple Music": "AppleInc.AppleMusic_8wekyb3d8bbwe!App"}
            ),
        },
    )()
    monkeypatch.setattr(app_resolver, "windowsapps", fake_windowsapps, raising=False)

    # Partial match — the query id is a substring of the registered aid
    result = app_resolver._resolve_app_name_from_aumid("AppleInc.AppleMusic_8wekyb3d8bbwe")
    assert result == "Apple Music"


def test_resolve_from_aumid_falls_back_to_registry_when_no_match(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)

    fake_windowsapps = type(
        "windowsapps",
        (),
        {
            "find_app_by_id": staticmethod(lambda app_id: "Application not found!"),
            "get_apps": staticmethod(lambda: {}),
        },
    )()
    monkeypatch.setattr(app_resolver, "windowsapps", fake_windowsapps, raising=False)
    # Patch registry to return None
    monkeypatch.setattr(app_resolver, "_resolve_from_registry", lambda app_id: None)

    result = app_resolver._resolve_app_name_from_aumid("unknown.app.id")
    assert result is None


def test_resolve_from_aumid_falls_back_to_registry_on_windowsapps_exception(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app_resolver, "WINDOWSAPPS_AVAILABLE", True)

    fake_windowsapps = type(
        "windowsapps",
        (),
        {
            "find_app_by_id": staticmethod(
                lambda app_id: (_ for _ in ()).throw(RuntimeError("oops"))
            )
        },
    )()
    monkeypatch.setattr(app_resolver, "windowsapps", fake_windowsapps, raising=False)
    monkeypatch.setattr(app_resolver, "_resolve_from_registry", lambda app_id: "fallback")

    result = app_resolver._resolve_app_name_from_aumid("some.app")
    assert result == "fallback"


# ── _resolve_from_registry ────────────────────────────────────────────────────


def test_resolve_from_registry_returns_none_without_winreg(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert app_resolver._resolve_from_registry("some.app") is None


def test_resolve_from_registry_returns_display_name(monkeypatch):
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_query(key, name):
        if name == "DisplayName":
            return ("My App", 1)
        raise OSError

    fake_winreg = type(
        "winreg",
        (),
        {
            "HKEY_CURRENT_USER": 0,
            "HKEY_CLASSES_ROOT": 1,
            "OpenKey": staticmethod(lambda hive, path: FakeKey()),
            "QueryValueEx": staticmethod(fake_query),
        },
    )()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    result = app_resolver._resolve_from_registry("some.app.id")
    assert result == "My App"


def test_resolve_from_registry_extracts_exe_from_relaunch_command(monkeypatch):
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_query(key, name):
        if name == "RelaunchCommand":
            return (r"C:\Program Files\MyApp\myapp.exe --launch", 1)
        raise OSError

    fake_winreg = type(
        "winreg",
        (),
        {
            "HKEY_CURRENT_USER": 0,
            "HKEY_CLASSES_ROOT": 1,
            "OpenKey": staticmethod(lambda hive, path: FakeKey()),
            "QueryValueEx": staticmethod(fake_query),
        },
    )()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    result = app_resolver._resolve_from_registry("some.app.id")
    assert result == "myapp.exe"


def test_resolve_from_registry_returns_none_when_key_missing(monkeypatch):
    def raise_oserror(hive, path):
        raise OSError("key not found")

    fake_winreg = type(
        "winreg",
        (),
        {
            "HKEY_CURRENT_USER": 0,
            "HKEY_CLASSES_ROOT": 1,
            "OpenKey": staticmethod(raise_oserror),
        },
    )()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    result = app_resolver._resolve_from_registry("missing.app")
    assert result is None
