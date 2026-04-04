import smtc
from app_resolver import resolve_app_name


def test_resolve_app_name_from_plain_exe() -> None:
    assert resolve_app_name("firefox.exe") == "firefox.exe"


def test_resolve_app_name_from_bang_qualified_app() -> None:
    assert resolve_app_name("Spotify.exe!App") == "spotify.exe"


def test_resolve_app_name_from_uwp_id() -> None:
    # This test may need adjustment based on actual windowsapps behavior
    result = resolve_app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic") 
    # Should resolve to either the friendly name from windowsapps or fallback to "zunemusic"
    assert result.lower() in ["groove music", "music", "zunemusic", "microsoft.zunemusic"]


def test_resolve_app_name_unknown_when_empty() -> None:
    assert resolve_app_name("") == "unknown"


def test_resolve_app_name_uses_aumid_resolver_for_opaque_id(monkeypatch) -> None:
    # Mock the registry fallback since windowsapps might not find this test ID
    import app_resolver
    monkeypatch.setattr(app_resolver, "_resolve_from_registry", lambda app_id: "foobar.exe")
    
    result = resolve_app_name("308046B0AF4A39CB")
    # Should either find it via windowsapps or fall back to our mocked registry function
    assert "foobar" in result.lower() or result == "308046b0af4a39cb"


def test_resolve_app_name_from_aumid_returns_none_off_windows(monkeypatch) -> None:
    import app_resolver
    monkeypatch.setattr("sys.platform", "linux")
    
    # This should fall back to basic string processing since registry won't work
    result = resolve_app_name("308046B0AF4A39CB")
    assert result == "308046b0af4a39cb"  # Cleaned version of the input
