# -*- coding: utf-8 -*-
"""
SkillRouter — rule-based skill selection.

Selects which trading skills to apply based on:
1. User-explicit request (highest priority)
2. Market regime detection from technical data in ``AgentContext``
3. Centralised default fallback
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.agent.protocols import AgentContext
from src.agent.skills.defaults import (
    get_default_router_skill_ids,
    get_regime_skill_ids,
)

logger = logging.getLogger(__name__)


class SkillRouter:
    """Select applicable skills for a given analysis context."""

    # Chip-structure thresholds for skill filtering.
    # "Trapped" means the vast majority of holders are underwater;
    # bottom/volume skills are near-useless in that regime.
    _CHIP_TRAPPED_PROFIT_RATIO = 0.30   # < 30% in profit → trapped
    _CHIP_OVERBOUGHT_PROFIT_RATIO = 0.80  # > 80% in profit → overbought

    # Skills that are ineffective when the stock is deeply trapped.
    _TRAPPED_SKIP_SKILLS: frozenset[str] = frozenset({
        "bottom_volume",     # relies on volume expansion + bottom formation
        "volume_breakout",   # breakout above trapped zone extremely unlikely
    })

    # Skills that are risky when overbought (profit-taking imminent).
    _OVERBOUGHT_SKIP_SKILLS: frozenset[str] = frozenset({
        "shrink_pullback",   # pullback from overbought = likely distribution
    })

    def select_skills(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        # Allow config override via AGENT_SKILL_MAX_COUNT
        config_max = self._get_config_max_count()
        if config_max is not None:
            max_count = config_max
        requested_skills = ctx.meta.get("skills_requested") or ctx.meta.get("strategies_requested", [])
        if requested_skills:
            logger.info("[SkillRouter] user-requested skills: %s", requested_skills)
            return requested_skills[:max_count]

        routing_mode = self._get_routing_mode()
        if routing_mode == "manual":
            selected = self._get_manual_skills(max_count=max_count)
            logger.info("[SkillRouter] manual mode — using skills: %s", selected)
            return selected

        available_skills = self._get_available_skills()
        skill_catalog = available_skills or None
        available_ids = {skill.name for skill in available_skills}
        regime = self._detect_regime(ctx)
        if regime:
            selected = get_regime_skill_ids(
                regime,
                skill_catalog,
                max_count=max_count,
                available_skill_ids=available_ids or None,
            )
            if selected:
                logger.info("[SkillRouter] regime=%s -> skills: %s", regime, selected)
                filtered = self._apply_chip_aware_filter(selected, ctx)
                if filtered != selected:
                    logger.info("[SkillRouter] chip filter: %s -> %s", selected, filtered)
                return filtered

        default_skills = get_default_router_skill_ids(
            skill_catalog,
            max_count=max_count,
            available_skill_ids=available_ids or None,
        )
        filtered = self._apply_chip_aware_filter(default_skills, ctx)
        if filtered != default_skills:
            logger.info("[SkillRouter] chip filter (default): %s -> %s", default_skills, filtered)
        logger.info("[SkillRouter] using default skills: %s", filtered)
        return filtered

    def select_strategies(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.select_skills(ctx, max_count=max_count)

    def _detect_regime(self, ctx: AgentContext) -> Optional[str]:
        for op in ctx.opinions:
            if op.agent_name != "technical":
                continue
            raw = op.raw_data or {}

            ma_alignment = str(raw.get("ma_alignment", "")).lower()
            # Fuzzy match: also accept partial/variant strings
            if "bull" in ma_alignment:
                ma_alignment = "bullish"
            elif "bear" in ma_alignment:
                ma_alignment = "bearish"

            try:
                trend_score = float(raw.get("trend_score", 50))
            except (TypeError, ValueError):
                trend_score = 50.0
            volume_status = str(raw.get("volume_status", "")).lower()

            if ma_alignment == "bullish" and trend_score >= 70:
                return "trending_up"
            if ma_alignment == "bearish" and trend_score <= 30:
                return "trending_down"
            if ma_alignment == "neutral" or 35 <= trend_score <= 65:
                return "sideways"
            if volume_status == "heavy" and 30 < trend_score < 70:
                return "volatile"

        if ctx.meta.get("sector_hot"):
            return "sector_hot"
        return None

    @classmethod
    def _apply_chip_aware_filter(
        cls,
        selected: list[str],
        ctx: AgentContext,
    ) -> list[str]:
        """Remove skills incompatible with the current chip structure.

        Rationale
        --------
        - **Trapped** (profit_ratio < 30 %): bottom/volume skills are
          noise — there is no "bottom" to detect, just dead-cat bounces.
          Drop ``bottom_volume`` and ``volume_breakout``.
        - **Overbought** (profit_ratio > 80 %): pullback from this zone
          is likely profit-taking distribution.  Drop ``shrink_pullback``.

        The filter is *conservative*: it never removes ALL skills.
        At least one skill is always kept so the analysis still runs.
        """
        chip = ctx.data.get("chip_distribution")
        profit_ratio: float | None = None
        if isinstance(chip, dict):
            try:
                profit_ratio = float(chip.get("profit_ratio", 0.5))
            except (TypeError, ValueError):
                profit_ratio = None

        if profit_ratio is None:
            return selected  # no chip data → no filter

        to_skip: set[str] = set()

        if profit_ratio < cls._CHIP_TRAPPED_PROFIT_RATIO:
            to_skip.update(cls._TRAPPED_SKIP_SKILLS)
        elif profit_ratio > cls._CHIP_OVERBOUGHT_PROFIT_RATIO:
            to_skip.update(cls._OVERBOUGHT_SKIP_SKILLS)

        if not to_skip:
            return selected

        filtered = [s for s in selected if s not in to_skip]
        if not filtered:
            # Safety: never empty the skill list entirely
            filtered = [selected[0]]

        if len(filtered) < len(selected):
            logger.info(
                "[SkillRouter] chip-aware filter: profit=%.1f%% removed=%s kept=%s",
                profit_ratio * 100,
                [s for s in selected if s not in filtered],
                filtered,
            )
        return filtered

    @staticmethod
    def _get_routing_mode() -> str:
        try:
            from src.config import get_config

            config = get_config()
            return getattr(config, "agent_skill_routing", "auto")
        except Exception:
            logger.warning("Failed to get routing mode, falling back to auto", exc_info=True)
            return "auto"

    @staticmethod
    def _get_config_max_count() -> int | None:
        """Read AGENT_SKILL_MAX_COUNT from config, returns None if not set."""
        try:
            from src.config import get_config

            config = get_config()
            raw = getattr(config, "agent_skill_max_count", None)
            if raw is not None:
                return max(1, min(int(raw), 6))
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _get_available_ids() -> set:
        return {skill.name for skill in SkillRouter._get_available_skills()}

    @staticmethod
    def _get_available_skills() -> list:
        try:
            from src.agent.factory import _SKILL_MANAGER_PROTOTYPE

            if _SKILL_MANAGER_PROTOTYPE is not None:
                return list(_SKILL_MANAGER_PROTOTYPE.list_skills())

            from src.agent.factory import get_skill_manager

            sm = get_skill_manager()
            return list(sm.list_skills())
        except Exception:
            logger.warning("Failed to get available skills", exc_info=True)
            return []

    @classmethod
    def _get_manual_skills(cls, max_count: int) -> List[str]:
        configured: List[str] = []
        try:
            from src.config import get_config

            config = get_config()
            configured = [
                skill_id
                for skill_id in getattr(config, "agent_skills", []) or []
                if isinstance(skill_id, str) and skill_id
            ]
        except Exception:
            logger.warning("Failed to get manual skills config", exc_info=True)
            configured = []

        available_skills = cls._get_available_skills()
        skill_catalog = available_skills or None
        available = {skill.name for skill in available_skills}
        selected = [skill_id for skill_id in configured if skill_id in available][:max_count]
        if selected:
            return selected

        return get_default_router_skill_ids(
            skill_catalog,
            max_count=max_count,
            available_skill_ids=available or None,
        )


StrategyRouter = SkillRouter
_DEFAULT_STRATEGIES = tuple(get_default_router_skill_ids())
_DEFAULT_SKILLS = _DEFAULT_STRATEGIES
