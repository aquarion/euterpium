# tests/test_fingerprint.py — ACRCloud signature building and response parsing

import base64
import hashlib
import hmac

import pytest

import fingerprint
from fingerprint import (
    _build_signature,
    _dominant_script,
    _pick_field,
    _pick_lang,
    _preferred_script,
)

# ── Signature generation ──────────────────────────────────────────────────────


def test_build_signature_matches_manual_computation():
    key = "testkey"
    secret = "testsecret"
    timestamp = "1700000000"

    string_to_sign = "\n".join(["POST", "/v1/identify", key, "audio", "1", timestamp])
    expected = base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()

    assert _build_signature(timestamp, key, secret) == expected


def test_build_signature_is_deterministic():
    sig1 = _build_signature("12345", "key", "secret")
    sig2 = _build_signature("12345", "key", "secret")
    assert sig1 == sig2


def test_build_signature_differs_on_timestamp():
    sig1 = _build_signature("1000", "key", "secret")
    sig2 = _build_signature("2000", "key", "secret")
    assert sig1 != sig2


def test_build_signature_differs_on_key():
    sig1 = _build_signature("1000", "key_a", "secret")
    sig2 = _build_signature("1000", "key_b", "secret")
    assert sig1 != sig2


def test_build_signature_differs_on_secret():
    sig1 = _build_signature("1000", "key", "secret_a")
    sig2 = _build_signature("1000", "key", "secret_b")
    assert sig1 != sig2


def test_build_signature_is_base64():
    sig = _build_signature("1700000000", "key", "secret")
    # Should decode without error
    decoded = base64.b64decode(sig)
    assert len(decoded) == 20  # SHA-1 digest is 20 bytes


# ── identify_audio ────────────────────────────────────────────────────────────


@pytest.fixture
def configured_credentials(monkeypatch):
    """Patch config to return valid ACRCloud credentials."""
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_access_key", lambda: "mykey")
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_access_secret", lambda: "mysecret")
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_host", lambda: "identify.acrcloud.com")
    monkeypatch.setattr(fingerprint.time, "time", lambda: 1700000000)


def _make_response(json_data, status_code=200):
    class FakeResponse:
        def raise_for_status(self):
            if status_code >= 400:
                raise fingerprint.requests.HTTPError(response=self)

        def json(self):
            return json_data

    return FakeResponse()


def test_identify_audio_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_access_key", lambda: "")
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_access_secret", lambda: "")
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_host", lambda: "identify.acrcloud.com")
    assert fingerprint.identify_audio(b"audio") is None


def test_identify_audio_returns_none_on_request_exception(monkeypatch, configured_credentials):
    def raise_exc(*args, **kwargs):
        raise fingerprint.requests.RequestException("network error")

    monkeypatch.setattr(fingerprint.requests, "post", raise_exc)
    assert fingerprint.identify_audio(b"audio") is None


def test_identify_audio_returns_none_on_no_match(monkeypatch, configured_credentials):
    response = _make_response({"status": {"code": 1001, "msg": "No result"}})
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    assert fingerprint.identify_audio(b"audio") is None


def test_identify_audio_returns_none_on_error_status(monkeypatch, configured_credentials):
    response = _make_response({"status": {"code": 3000, "msg": "Internal error"}})
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    assert fingerprint.identify_audio(b"audio") is None


def test_identify_audio_returns_result_on_success(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "Answers",
                        "artists": [{"name": "Susan Calloway"}],
                        "album": {"name": "Final Fantasy XIV"},
                        "release_date": "2013-09-10",
                        "acrid": "abc123",
                        "external_metadata": {},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)

    result = fingerprint.identify_audio(b"audio")

    assert result is not None
    assert result["source"] == "acrcloud"
    assert result["title"] == "Answers"
    assert result["artist"] == "Susan Calloway"
    assert result["album"] == "Final Fantasy XIV"
    assert result["release_date"] == "2013-09-10"
    assert result["acrid"] == "abc123"
    assert result["streaming_links"] == {}


def test_identify_audio_includes_streaming_links(monkeypatch, configured_credentials):
    external_metadata = {
        "spotify": {
            "track": {"id": "spotify_track_id"},
            "artists": [{"id": "artist_id"}],
            "album": {"id": "album_id"},
        },
        "deezer": {
            "track": {"id": "deezer_track_id"},
            "artists": [{"id": "artist_id"}],
            "album": {"id": "album_id"},
        },
        "youtube": {"vid": "youtube_vid"},
        "musicbrainz": [{"track": {"id": "mb_track_id"}}],
    }
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "Answers",
                        "artists": [{"name": "Susan Calloway"}],
                        "album": {},
                        "release_date": "",
                        "acrid": "abc123",
                        "external_metadata": external_metadata,
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)

    result = fingerprint.identify_audio(b"audio")

    assert result is not None
    assert result["streaming_links"] == external_metadata


def test_identify_audio_returns_none_on_malformed_response(monkeypatch, configured_credentials):
    # Missing expected keys in metadata
    response = _make_response({"status": {"code": 0, "msg": "Success"}, "metadata": {}})
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    assert fingerprint.identify_audio(b"audio") is None


def test_identify_audio_posts_to_correct_url(monkeypatch, configured_credentials):
    posted_urls = []

    def fake_post(url, **kwargs):
        posted_urls.append(url)
        return _make_response({"status": {"code": 1001, "msg": "No result"}})

    monkeypatch.setattr(fingerprint.requests, "post", fake_post)
    fingerprint.identify_audio(b"audio")

    assert posted_urls == ["https://identify.acrcloud.com/v1/identify"]


# ── _dominant_script ──────────────────────────────────────────────────────────


def test_dominant_script_latin():
    assert _dominant_script("Masayoshi Soken") == "latin"


def test_dominant_script_cjk_kanji():
    assert _dominant_script("祖堅正慶") == "cjk"


def test_dominant_script_cjk_hiragana():
    assert _dominant_script("あいうえお") == "cjk"


def test_dominant_script_hangul():
    assert _dominant_script("마마무") == "hangul"


def test_dominant_script_cyrillic():
    assert _dominant_script("Земфира") == "cyrillic"


def test_dominant_script_unknown_for_punctuation():
    assert _dominant_script("!!!") == "unknown"


def test_dominant_script_empty_string():
    assert _dominant_script("") == "unknown"


# ── _preferred_script ─────────────────────────────────────────────────────────


def test_preferred_script_en_is_latin():
    assert _preferred_script("en") == "latin"


def test_preferred_script_en_gb_is_latin():
    assert _preferred_script("en-GB") == "latin"


def test_preferred_script_ja_is_cjk():
    assert _preferred_script("ja") == "cjk"


def test_preferred_script_zh_hans_is_cjk():
    assert _preferred_script("zh-Hans") == "cjk"


def test_preferred_script_zh_hans_cn_is_cjk():
    assert _preferred_script("zh-Hans-CN") == "cjk"


def test_preferred_script_ko_is_hangul():
    assert _preferred_script("ko") == "hangul"


def test_preferred_script_ru_is_cyrillic():
    assert _preferred_script("ru") == "cyrillic"


def test_preferred_script_unknown_code_defaults_to_latin():
    assert _preferred_script("xx-Unknown") == "latin"


def test_preferred_script_empty_string_defaults_to_latin():
    assert _preferred_script("") == "latin"


# ── _pick_lang ────────────────────────────────────────────────────────────────


def test_pick_lang_exact_match():
    langs = [{"code": "zh-Hans", "name": "你好"}]
    assert _pick_lang("Hello", langs, "zh-Hans") == "你好"


def test_pick_lang_prefix_match_strips_region():
    langs = [{"code": "en", "name": "Hello"}]
    assert _pick_lang("Hola", langs, "en-GB") == "Hello"


def test_pick_lang_multi_level_strip():
    langs = [{"code": "zh-Hans", "name": "你好"}]
    assert _pick_lang("Hello", langs, "zh-Hans-CN") == "你好"


def test_pick_lang_no_match_returns_primary():
    langs = [{"code": "ja", "name": "こんにちは"}]
    assert _pick_lang("Hello", langs, "en") == "Hello"


def test_pick_lang_empty_langs_returns_primary():
    assert _pick_lang("Hello", [], "en") == "Hello"


def test_pick_lang_empty_preferred_returns_primary():
    langs = [{"code": "en", "name": "Hello"}]
    assert _pick_lang("Hola", langs, "") == "Hola"


def test_pick_lang_skips_entry_with_missing_name():
    langs = [{"code": "en"}, {"code": "en", "name": "Hello"}]
    assert _pick_lang("Hola", langs, "en") == "Hello"


def test_pick_lang_falls_back_when_only_match_has_missing_name():
    langs = [{"code": "en"}]
    assert _pick_lang("Hola", langs, "en") == "Hola"


# ── _pick_field ───────────────────────────────────────────────────────────────


def test_pick_field_returns_entry_in_preferred_script():
    entries = [
        {"title": "祖堅正慶"},
        {"title": "Masayoshi Soken"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "Masayoshi Soken"


def test_pick_field_falls_back_to_first_when_no_match():
    entries = [
        {"title": "祖堅正慶"},
        {"title": "最終幻想"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "祖堅正慶"


def test_pick_field_returns_first_when_it_already_matches():
    entries = [
        {"title": "Masayoshi Soken"},
        {"title": "祖堅正慶"},
    ]
    assert _pick_field(entries, lambda e: e["title"], "latin") == "Masayoshi Soken"


# ── identify_audio — language selection ──────────────────────────────────────


def test_identify_audio_picks_title_from_langs(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "你好",
                        "langs": [{"code": "en", "name": "Hello"}],
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc",
                        "external_metadata": {},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["title"] == "Hello"


def test_identify_audio_picks_artist_by_script_scan(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "The Aetherial Sea",
                        "artists": [{"name": "祖堅正慶"}],
                        "album": {"name": "ENDWALKER: FINAL FANTASY XIV Original Soundtrack"},
                        "release_date": "2022-02-23",
                        "acrid": "abc1",
                        "external_metadata": {},
                    },
                    {
                        "title": "The Aetherial Sea",
                        "artists": [{"name": "Masayoshi Soken"}],
                        "album": {"name": "ENDWALKER: FINAL FANTASY XIV Original Soundtrack"},
                        "release_date": "2022-02-23",
                        "acrid": "abc2",
                        "external_metadata": {},
                    },
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["artist"] == "Masayoshi Soken"


def test_identify_audio_script_scan_falls_back_to_first_entry(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "曲名",
                        "artists": [{"name": "アーティスト"}],
                        "album": {"name": "アルバム"},
                        "release_date": "",
                        "acrid": "abc",
                        "external_metadata": {},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["artist"] == "アーティスト"


def test_identify_audio_langs_title_and_script_scan_artist(monkeypatch, configured_credentials):
    response = _make_response(
        {
            "status": {"code": 0, "msg": "Success"},
            "metadata": {
                "music": [
                    {
                        "title": "你好",
                        "langs": [{"code": "en", "name": "Hello"}],
                        "artists": [{"name": "祖堅正慶"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc1",
                        "external_metadata": {},
                    },
                    {
                        "title": "你好",
                        "artists": [{"name": "Masayoshi Soken"}],
                        "album": {"name": "Album"},
                        "release_date": "",
                        "acrid": "abc2",
                        "external_metadata": {},
                    },
                ]
            },
        }
    )
    monkeypatch.setattr(fingerprint.requests, "post", lambda *a, **kw: response)
    monkeypatch.setattr(fingerprint.config, "get_acrcloud_language", lambda: "en")

    result = fingerprint.identify_audio(b"audio")
    assert result["title"] == "Hello"
    assert result["artist"] == "Masayoshi Soken"
