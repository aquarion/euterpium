# tests/test_config.py — config read/write, profiles, migration, validation

import logging

import config

# ── Configured checks ─────────────────────────────────────────────────────────


def test_acrcloud_not_configured_when_empty(tmp_config):
    assert config.acrcloud_is_configured() is False


def test_acrcloud_configured_when_both_fields_set(tmp_config):
    config.save({"acrcloud": {"access_key": "mykey", "access_secret": "mysecret"}})
    assert config.acrcloud_is_configured() is True


def test_acrcloud_not_configured_with_only_key(tmp_config):
    config.save({"acrcloud": {"access_key": "mykey", "access_secret": ""}})
    assert config.acrcloud_is_configured() is False


def test_api_not_configured_when_empty(tmp_config):
    assert config.api_is_configured() is False


def test_api_not_configured_for_placeholder_url(tmp_config):
    config.save(
        {
            "api": {"active": "dev"},
            "api:dev": {"url": "https://your-api.com/now-playing", "key": ""},
        }
    )
    assert config.api_is_configured() is False


def test_api_configured_with_real_url(tmp_config):
    config.save(
        {"api": {"active": "dev"}, "api:dev": {"url": "https://example.com/api", "key": ""}}
    )
    assert config.api_is_configured() is True


def test_is_configured_requires_both(tmp_config):
    # Neither configured
    assert config.is_configured() is False

    # Only ACRCloud
    config.save({"acrcloud": {"access_key": "k", "access_secret": "s"}})
    assert config.is_configured() is False

    # Both
    config.save(
        {"api": {"active": "dev"}, "api:dev": {"url": "https://example.com/api", "key": ""}}
    )
    assert config.is_configured() is True


# ── Multi-profile API ─────────────────────────────────────────────────────────


def test_get_api_profiles_empty(tmp_config):
    assert config.get_api_profiles() == {}


def test_get_api_profiles_returns_all_sections(tmp_config):
    config.save(
        {
            "api:dev": {"url": "http://dev.example.com", "key": "devkey"},
            "api:live": {"url": "http://live.example.com", "key": "livekey"},
        }
    )
    profiles = config.get_api_profiles()
    assert set(profiles.keys()) == {"dev", "live"}
    assert profiles["dev"]["url"] == "http://dev.example.com"
    assert profiles["live"]["key"] == "livekey"


def test_get_api_url_for_named_profile(tmp_config):
    config.save({"api:stage": {"url": "http://stage.example.com", "key": ""}})
    assert config.get_api_url("stage") == "http://stage.example.com"


def test_get_api_url_uses_active_profile(tmp_config):
    config.save(
        {
            "api": {"active": "live"},
            "api:dev": {"url": "http://dev.example.com", "key": ""},
            "api:live": {"url": "http://live.example.com", "key": ""},
        }
    )
    assert config.get_api_url() == "http://live.example.com"


def test_get_api_key_for_named_profile(tmp_config):
    config.save({"api:prod": {"url": "http://example.com", "key": "secretkey"}})
    assert config.get_api_key("prod") == "secretkey"


def test_get_active_profile(tmp_config):
    config.save({"api": {"active": "live"}})
    assert config.get_active_profile() == "live"


def test_get_active_profile_default_empty(tmp_config):
    assert config.get_active_profile() == ""


# ── Save and reload ───────────────────────────────────────────────────────────


def test_save_and_reload_acrcloud(tmp_config):
    config.save({"acrcloud": {"host": "identify-us-west-2.acrcloud.com"}})
    assert config.get_acrcloud_host() == "identify-us-west-2.acrcloud.com"


def test_save_merges_rather_than_overwrites(tmp_config):
    config.save({"acrcloud": {"access_key": "key1"}})
    config.save({"acrcloud": {"access_secret": "secret1"}})
    assert config.get_acrcloud_access_key() == "key1"
    assert config.get_acrcloud_access_secret() == "secret1"


def test_save_returns_true_on_success(tmp_config):
    result = config.save({"acrcloud": {"access_key": "k"}})
    assert result is True


def test_save_returns_false_when_unavailable(monkeypatch):
    monkeypatch.setattr(config, "_CONFIG_UNAVAILABLE", True)
    result = config.save({"acrcloud": {"access_key": "k"}})
    assert result is False


# ── Legacy migration ──────────────────────────────────────────────────────────


def test_migrate_legacy_api(tmp_config):
    tmp_config.write_text("[api]\nurl = http://legacy.example.com\nkey = oldkey\n")
    config._migrate_legacy_api()
    profiles = config.get_api_profiles()
    assert "dev" in profiles
    assert profiles["dev"]["url"] == "http://legacy.example.com"
    assert profiles["dev"]["key"] == "oldkey"
    assert config.get_active_profile() == "dev"


def test_migrate_skips_when_profiles_exist(tmp_config):
    tmp_config.write_text("[api]\nactive = dev\n[api:dev]\nurl = http://dev.example.com\nkey =\n")
    config._migrate_legacy_api()
    # Should not have added a second profile
    profiles = config.get_api_profiles()
    assert list(profiles.keys()) == ["dev"]


def test_migrate_skips_when_legacy_url_is_placeholder(tmp_config):
    tmp_config.write_text("[api]\nurl = https://your-api.com/now-playing\nkey =\n")
    config._migrate_legacy_api()
    assert config.get_api_profiles() == {}


# ── Numeric fallbacks ─────────────────────────────────────────────────────────


def test_getint_falls_back_on_non_numeric(tmp_config):
    config.save({"audio": {"sample_rate": "fast"}})
    cfg = config._load()
    assert config._getint(cfg, "audio", "sample_rate", 44100) == 44100


def test_getfloat_falls_back_on_non_numeric(tmp_config):
    config.save({"audio": {"capture_seconds": "long"}})
    cfg = config._load()
    assert config._getfloat(cfg, "audio", "capture_seconds", 10.0) == 10.0


def test_getint_returns_valid_value(tmp_config):
    config.save({"audio": {"sample_rate": "22050"}})
    cfg = config._load()
    assert config._getint(cfg, "audio", "sample_rate", 44100) == 22050


# ── Logging level ─────────────────────────────────────────────────────────────


def test_get_log_level_default_is_info(tmp_config):
    assert config.get_log_level() == logging.INFO


def test_get_log_level_returns_debug(tmp_config):
    config.save({"logging": {"level": "DEBUG"}})
    assert config.get_log_level() == logging.DEBUG


def test_get_log_level_case_insensitive(tmp_config):
    config.save({"logging": {"level": "warning"}})
    assert config.get_log_level() == logging.WARNING


def test_get_log_level_falls_back_to_info_on_invalid(tmp_config):
    config.save({"logging": {"level": "NOTAVALIDLEVEL"}})
    assert config.get_log_level() == logging.INFO
