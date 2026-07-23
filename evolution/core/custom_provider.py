"""Custom LLM provider — reuses Hermes Agent's current provider.

Reads base_url, api_key, and model from Hermes config, so no separate
API key setup is needed. Override any setting via env vars or CLI args.

Priority: CLI args > env vars > Hermes config > defaults.
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dspy


# ── Hermes config discovery ─────────────────────────────────────────

_HERMES_CONFIG_PATHS = [
    Path.home() / ".hermes" / "config.yaml",
    Path.home() / ".hermes" / "profiles" / "default" / "config.yaml",
]


def _load_hermes_config() -> dict:
    """Read the first existing Hermes config file."""
    for p in _HERMES_CONFIG_PATHS:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}


def _find_custom_provider_config(config: dict) -> dict:
    """Extract the custom provider section from Hermes config.

    Hermes stores custom providers under auxiliary.* or as
    'custom:<hostname>' in model.provider. We look for base_url + api_key.
    """
    # Check auxiliary sections for base_url / api_key
    aux = config.get("auxiliary", {})
    for section in aux.values():
        if isinstance(section, dict):
            base_url = section.get("base_url", "")
            api_key = section.get("api_key", "")
            if base_url and api_key:
                return {"base_url": base_url, "api_key": api_key}

    # Fallback: construct from provider string
    provider_str = config.get("model", {}).get("provider", "")
    if provider_str.startswith("custom:"):
        hostname = provider_str.split(":", 1)[1]
        return {
            "base_url": f"https://{hostname}/v1",
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
        }

    return {}


# ── Public config ───────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Resolved LLM provider configuration."""
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    temperature: float = 0.0
    max_tokens: int = 4096

    @classmethod
    def resolve(
        cls,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> "LLMConfig":
        """Build config with priority: args > env > hermes config > defaults."""
        hermes = _load_hermes_config()
        provider_cfg = _find_custom_provider_config(hermes)

        return cls(
            base_url=base_url
                or os.environ.get("OPENAI_API_BASE", "")
                or provider_cfg.get("base_url", ""),
            api_key=api_key
                or os.environ.get("OPENAI_API_KEY", "")
                or provider_cfg.get("api_key", ""),
            model=model
                or os.environ.get("EVOLUTION_MODEL", "")
                or hermes.get("model", {}).get("default", "gpt-4.1-mini"),
            temperature=temperature if temperature is not None else 0.0,
            max_tokens=max_tokens or 4096,
        )


# ── DSPy integration ────────────────────────────────────────────────

def configure_dspy(cfg: Optional[LLMConfig] = None) -> LLMConfig:
    """Configure DSPy to use the resolved provider.

    Returns the LLMConfig used, so callers can log/display it.
    """
    if cfg is None:
        cfg = LLMConfig.resolve()

    if not cfg.base_url:
        raise ValueError(
            "No LLM base_url found. Set OPENAI_API_BASE env var, "
            "or configure a custom provider in ~/.hermes/config.yaml"
        )

    if not cfg.api_key:
        raise ValueError(
            "No LLM api_key found. Set OPENAI_API_KEY env var, "
            "or configure a custom provider in ~/.hermes/config.yaml"
        )

    # Set env vars so DSPy's OpenAI client picks them up
    os.environ["OPENAI_API_BASE"] = cfg.base_url
    os.environ["OPENAI_API_KEY"] = cfg.api_key

    # Configure DSPy with the model
    lm = dspy.LM(
        model=cfg.model,
        api_base=cfg.base_url,
        api_key=cfg.api_key,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    dspy.configure(lm=lm)

    return cfg


def get_model_name(cfg: Optional[LLMConfig] = None) -> str:
    """Return the resolved model name for display."""
    if cfg is None:
        cfg = LLMConfig.resolve()
    return cfg.model
