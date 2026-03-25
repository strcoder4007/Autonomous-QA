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
class LLMConfig:
    model: str = "gpt-5-mini"
    api_key_env: str = "OPENAI_API_KEY"
    max_tokens: int = 4096
    temperature: float = 0.2
    batch_size: int = 5


@dataclass
class Config:
    base_url: str = ""
    auth: AuthConfig = field(default_factory=AuthConfig)
    request_delay_ms: int = 0
    timeout_seconds: int = 10
    verify_ssl: bool = True
    seed_params: dict[str, str] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)


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
    # base_url is not required at config-load time; commands that need it (e.g. run, generate --execute)
    # must validate its presence themselves before making requests.
    base_url = cli_base_url or env_data.get("BASE_URL") or yaml_data.get("base_url") or ""

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

    # --- Resolve LLM config ---
    llm_yaml = yaml_data.get("llm", {})
    llm = LLMConfig(
        model=llm_yaml.get("model", "gpt-5-mini"),
        api_key_env=llm_yaml.get("api_key_env", "OPENAI_API_KEY"),
        max_tokens=llm_yaml.get("max_tokens", 4096),
        temperature=llm_yaml.get("temperature", 0.2),
        batch_size=llm_yaml.get("batch_size", 5),
    )

    return Config(
        base_url=base_url.rstrip("/") if base_url else "",
        auth=auth,
        request_delay_ms=yaml_data.get("request_delay_ms", 0),
        timeout_seconds=yaml_data.get("timeout_seconds", 10),
        verify_ssl=yaml_data.get("verify_ssl", True),
        seed_params=seed_params,
        llm=llm,
    )
