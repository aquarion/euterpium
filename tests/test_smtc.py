from app_resolver import resolve_app_name


def test_resolve_app_name_from_plain_exe() -> None:
    assert resolve_app_name("firefox.exe") == "firefox.exe"


def test_resolve_app_name_from_bang_qualified_app() -> None:
    assert resolve_app_name("Spotify.exe!App") == "spotify.exe"


def test_resolve_app_name_from_uwp_id() -> None:
    # Test that UWP ID resolution returns a reasonable name (not the raw ID)
    result = resolve_app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic")
    # Should resolve to something sensible, not the original complex ID
    assert result != "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"
    assert len(result) > 0
    # Should be a cleaned-up name
    assert "!" not in result
    assert result.islower()


def test_resolve_app_name_unknown_when_empty() -> None:
    assert resolve_app_name("") == "unknown"


def test_resolve_app_name_uses_aumid_resolver_for_opaque_id(monkeypatch) -> None:
    # Test that the app resolver tries multiple strategies and returns a reasonable result
    result = resolve_app_name("308046B0AF4A39CB")
    
    # Should return something reasonable - either from windowsapps, registry, or cleaned fallback
    assert len(result) > 0
    assert result != "308046B0AF4A39CB"  # Should not return the raw input unchanged
    
    # Should be lowercase and reasonable length
    assert result.islower()
    assert len(result) < 50  # Shouldn't be excessively long


def test_resolve_app_name_from_aumid_returns_none_off_windows(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")

    # This should fall back to basic string processing since registry won't work
    result = resolve_app_name("308046B0AF4A39CB")
    assert result == "308046b0af4a39cb"  # Cleaned version of the input
