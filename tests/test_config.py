"""Tests for configuration loading."""

import json
import os
import pytest

from swaggertest.config import load_config


def test_load_config_from_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=https://staging.example.com\nAPI_TOKEN=secret123\n")

    cfg = load_config(
        config_path=str(tmp_path / "nonexistent.yaml"),
        env_path=str(env_file),
    )
    assert cfg.base_url == "https://staging.example.com"
    assert cfg.auth.token == "secret123"


def test_cli_overrides_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=https://from-env.example.com\n")

    cfg = load_config(
        cli_base_url="https://from-cli.example.com",
        config_path=str(tmp_path / "nonexistent.yaml"),
        env_path=str(env_file),
    )
    assert cfg.base_url == "https://from-cli.example.com"


def test_missing_base_url_raises(tmp_path):
    with pytest.raises(RuntimeError, match="BASE_URL is required"):
        load_config(
            config_path=str(tmp_path / "nonexistent.yaml"),
            env_path=str(tmp_path / "nonexistent.env"),
        )


def test_seed_params_loaded(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=https://example.com\n")

    seed_file = tmp_path / "seeds.json"
    seed_file.write_text(json.dumps({"id": "42", "userId": "abc"}))

    cfg = load_config(
        cli_seed_params=str(seed_file),
        config_path=str(tmp_path / "nonexistent.yaml"),
        env_path=str(env_file),
    )
    assert cfg.seed_params == {"id": "42", "userId": "abc"}
