# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 配置管理模块
===================================

This package replaces the monolithic ``src/config.py``.
Public symbols are re-exported from sub-modules so that existing
``from src.config import ...`` imports continue to work unchanged.
"""

# ---- Constants & helpers ----
from src.config.constants import (
    _FALSEY_ENV_VALUES,
    _get_litellm_provider,
    _has_gotify_base_url,
    _has_ntfy_topic_endpoint,
    _MANAGED_LITELLM_KEY_PROVIDERS,
    _uses_direct_env_provider,
    AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE,
    AGENT_CONTEXT_COMPRESSION_PROFILES,
    AGENT_MAX_STEPS_DEFAULT,
    ANSPIRE_LLM_BASE_URL_DEFAULT,
    ANSPIRE_LLM_MODEL_DEFAULT,
    FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT,
    NEWS_STRATEGY_WINDOWS,
    SUPPORTED_LLM_CHANNEL_PROTOCOLS,
    AgentContextCompressionPreset,
    ConfigIssue,
    canonicalize_llm_channel_protocol,
    channel_allows_empty_api_key,
    get_agent_context_compression_preset,
    get_configured_llm_models,
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
    get_fixed_litellm_temperature,
    normalize_agent_context_compression_profile,
    normalize_agent_litellm_model,
    normalize_llm_channel_model,
    normalize_litellm_temperature,
    normalize_news_strategy_profile,
    parse_agent_context_compression_int,
    parse_env_bool,
    parse_env_float,
    parse_env_int,
    resolve_llm_channel_protocol,
    resolve_litellm_thinking_enabled,
    resolve_litellm_wire_model,
    resolve_news_window_days,
    resolve_unified_llm_temperature,
)

# ---- Config class & singleton ----
from src.config.config import (
    Config,
    extra_litellm_params,
    get_api_keys_for_model,
    get_config,
    setup_env,
)
