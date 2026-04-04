from smtc import _source_app_name


def test_source_app_name_from_plain_exe() -> None:
    assert _source_app_name("firefox.exe") == "firefox.exe"


def test_source_app_name_from_bang_qualified_app() -> None:
    assert _source_app_name("Spotify.exe!App") == "spotify.exe"


def test_source_app_name_from_uwp_id() -> None:
    assert _source_app_name("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic") == "zunemusic"


def test_source_app_name_unknown_when_empty() -> None:
    assert _source_app_name("") == "unknown"
