"""Tests for custom provider — config resolution, env overrides."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from evolution.core.custom_provider import LLMConfig, _load_hermes_config, _find_custom_provider_config


class TestLoadHermesConfig:
    def test_reads_existing_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("model:\n  default: my-model\n  provider: custom:my-host.com\n")
        with patch("evolution.core.custom_provider._HERMES_CONFIG_PATHS", [config_file]):
            result = _load_hermes_config()
        assert result["model"]["default"] == "my-model"

    def test_returns_empty_on_missing(self, tmp_path):
        with patch("evolution.core.custom_provider._HERMES_CONFIG_PATHS", [tmp_path / "nonexistent.yaml"]):
            result = _load_hermes_config()
        assert result == {}


class TestFindCustomProviderConfig:
    def test_from_auxiliary_section(self):
        config = {
            "auxiliary": {
                "vision": {
                    "base_url": "https://my-host.com/v1",
                    "api_key": "sk-test123",
                }
            }
        }
        result = _find_custom_provider_config(config)
        assert result["base_url"] == "https://my-host.com/v1"
        assert result["api_key"] == "sk-test123"

    def test_from_provider_string(self):
        config = {"model": {"provider": "custom:my-host.example.com"}}
        result = _find_custom_provider_config(config)
        assert result["base_url"] == "https://my-host.example.com/v1"

    def test_empty_config(self):
        result = _find_custom_provider_config({})
        assert result == {}


class TestLLMConfigResolve:
    def test_defaults_when_nothing_set(self):
        with patch("evolution.core.custom_provider._HERMES_CONFIG_PATHS", []):
            with patch.dict(os.environ, {}, clear=True):
                cfg = LLMConfig.resolve()
        assert cfg.model == "gpt-4.1-mini"
        assert cfg.base_url == ""

    def test_env_var_override(self):
        with patch.dict(os.environ, {
            "OPENAI_API_BASE": "https://custom-api.com/v1",
            "OPENAI_API_KEY": "sk-env-key",
            "EVOLUTION_MODEL": "my-custom-model",
        }):
            cfg = LLMConfig.resolve()
        assert cfg.base_url == "https://custom-api.com/v1"
        assert cfg.api_key == "sk-env-key"
        assert cfg.model == "my-custom-model"

    def test_cli_arg_highest_priority(self):
        with patch.dict(os.environ, {
            "OPENAI_API_BASE": "https://env-url.com/v1",
            "OPENAI_API_KEY": "sk-env",
        }):
            cfg = LLMConfig.resolve(
                base_url="https://cli-url.com/v1",
                api_key="sk-cli",
                model="cli-model",
            )
        assert cfg.base_url == "https://cli-url.com/v1"
        assert cfg.api_key == "sk-cli"
        assert cfg.model == "cli-model"

    def test_hermes_config_fallback(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "model:\n  default: hermes-model\n  provider: custom:hermes-host.com\n"
            "auxiliary:\n  vision:\n    base_url: https://hermes-host.com/v1\n"
            "    api_key: sk-hermes\n"
        )
        with patch("evolution.core.custom_provider._HERMES_CONFIG_PATHS", [config_file]):
            cfg = LLMConfig.resolve()
        assert cfg.model == "hermes-model"
        assert cfg.base_url == "https://hermes-host.com/v1"
        assert cfg.api_key == "sk-hermes"

    def test_temperature_and_max_tokens(self):
        cfg = LLMConfig.resolve(temperature=0.5, max_tokens=8192)
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 8192
