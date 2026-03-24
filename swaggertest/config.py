"""Config precedence resolution and env-var injection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values


@dataclass
class AuthConfig:
    type: str = "bearer"  # bearer | api_key_header | api_key_query | basic
    token_env: str = "API_TOKEN"
    token: str | None = None


@dataclass
class Config:
    base_url: str = ""
    auth: AuthConfig = field(default_factory=AuthConfig)
    request_delay_ms: int = 0
    timeout_seconds: int = 10
    verify_ssl: bool = True
    seed_params: dict[str, str] = field(default_factory=dict)


def load_config(
    *,
    cli_base_url: str | None = None,
    cli_seed_params: str | None = None,
    config_path: str = ".swaggertest.yaml",
    env_path: str = ".env",
) -> Config:
    """Build a ``Config`` by merging CLI flags, .env, and .swaggertest.yaml (in that precedence)."""

    # --- Layer 1: .swaggertest.yaml (lowest precedence) ---
    yaml_data: dict[str, Any] = {}
    if Path(config_path).is_file():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # --- Layer 2: .env ---
    env_data: dict[str, str | None] = {}
    if Path(env_path).is_file():
        env_data = dotenv_values(env_path)

    # --- Resolve base_url ---
    base_url = cli_base_url or env_data.get("BASE_URL") or yaml_data.get("base_url") or ""
    if not base_url:
        raise RuntimeError(
            "BASE_URL is required but was not found in CLI flags, .env, or .swaggertest.yaml. "
            "Set it explicitly to avoid accidentally hitting production."
        )

    # --- Resolve auth ---
    auth_yaml = yaml_data.get("auth", {})
    auth_type = auth_yaml.get("type", "bearer")
    token_env = auth_yaml.get("token_env", "API_TOKEN")
    token = env_data.get(token_env) or os.environ.get(token_env)

    auth = AuthConfig(type=auth_type, token_env=token_env, token=token)

    # --- Resolve seed params ---
    seed_params_file = cli_seed_params or yaml_data.get("seed_params_file", "~/.swaggertest/seed_params.json")
    seed_params_path = Path(seed_params_file).expanduser()
    seed_params: dict[str, str] = {}
    if seed_params_path.is_file():
        with open(seed_params_path) as f:
            seed_params = json.load(f)

    return Config(
        base_url=base_url.rstrip("/"),
        auth=auth,
        request_delay_ms=yaml_data.get("request_delay_ms", 0),
        timeout_seconds=yaml_data.get("timeout_seconds", 10),
        verify_ssl=yaml_data.get("verify_ssl", True),
        seed_params=seed_params,
    )
