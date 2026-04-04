import smtc
from smtc import _source_app_name


def test_source_app_name_from_plain_exe() -> None:
    assert _source_app_name("firefox.exe") == "firefox.exe"


def test_source_app_name_from_bang_qualified_app() -> None:
    assert _source_app_name("Spotify.exe!App") == "spotify.exe"


def test_source_app_name_from_uwp_id() -> None:
    assert _source_app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic") == "zunemusic"


def test_source_app_name_unknown_when_empty() -> None:
    assert _source_app_name("") == "unknown"


def test_source_app_name_uses_aumid_resolver_for_opaque_id(monkeypatch) -> None:
    monkeypatch.setattr(smtc, "_resolve_app_name_from_aumid", lambda app_id: "foobar.exe")

    assert _source_app_name("308046B0AF4A39CB") == "foobar.exe"


def test_resolve_app_name_from_aumid_returns_none_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(smtc.sys, "platform", "linux")

    assert smtc._resolve_app_name_from_aumid("308046B0AF4A39CB") is None
