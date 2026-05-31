# -*- coding: utf-8 -*-
"""
Shared defaults for trading skills.

This module centralises:
1. The default active skill set used by agent entrypoints
2. The fallback skill subset used by the multi-agent router
3. Common prompt fragments that previously drifted across multiple files
4. Helper utilities for skill-specific agent naming
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "strategies"

SKILL_AGENT_PREFIX = "skill_"
LEGACY_STRATEGY_AGENT_PREFIX = "strategy_"
SKILL_CONSENSUS_AGENT_NAME = "skill_consensus"
LEGACY_STRATEGY_CONSENSUS_AGENT_NAME = "strategy_consensus"

CORE_TRADING_SKILL_POLICY_ZH = """## 默认技能基线（必须严格遵守）

当前激活的 skills 可以补充细化分析视角，但默认风险控制和交易节奏必须遵守以下基线。

### 1. 严进策略（不追高）
- **绝对不追高**：当股价偏离 MA5 超过 5% 时，坚决不买入
- 乖离率 < 2%：最佳买点区间
- 乖离率 2-5%：可小仓介入
- 乖离率 > 5%：严禁追高！直接判定为"观望"

### 2. 趋势交易（顺势而为）
- **多头排列必须条件**：MA5 > MA10 > MA20
- 只做多头排列的股票，空头排列坚决不碰
- 均线发散上行优于均线粘合

### 3. 效率优先（筹码结构）
- 关注筹码集中度：90%集中度 < 15% 表示筹码集中
- 获利比例分析：70-90% 获利盘时需警惕获利回吐
- 平均成本与现价关系：现价高于平均成本 5-15% 为健康

### 4. 买点偏好（回踩支撑）
- **最佳买点**：缩量回踩 MA5 获得支撑
- **次优买点**：回踩 MA10 获得支撑
- **观望情况**：跌破 MA20 时观望

### 5. 风险排查重点
- 减持公告、业绩预亏、监管处罚、行业政策利空、大额解禁

### 6. 估值关注（PE/PB）
- PE 明显偏高时需在风险点中说明

### 7. 强势趋势股放宽
- 强势趋势股可适当放宽乖离率要求，轻仓追踪但需设止损
"""

BEAR_MARKET_SKILL_POLICY_ZH = """## 空头市场基线（必须严格遵守）

当前行情处于空头/下跌趋势，以下基线优先级高于技能信号。

### 1. 防御优先（不抄底）
- **空头排列坚决不买**：MA5 < MA10 < MA20时，首要任务是保护资金
- 只在出现明确的底部反转信号（底背驰 + 放量阳线 + 站上MA5）后才考虑试探性仓位
- 绝不左侧抄底，等右侧确认信号

### 2. 止损纪律（严格）
- 任何持仓必须设止损，止损距离不超过入场价3%
- 跌破关键支撑（MA20/前低）立即无条件离场
- 反弹遇阻MA10/MA20时考虑减仓

### 3. 风险排查（最高优先级）
- 减持公告、业绩预亏、监管处罚、大额解禁 → 一票否决
- 资金持续流出（主力净流出）时不做多
- PE/PB异常偏高时在风险点中明确标注

### 4. 买点要求（极严格）
- 必须底背驰 + 放量（量比>1.5） + 站上MA5 三者同时满足
- 仅限试探仓位（≤2成），趋势确认后再加仓
- 乖离率必须<3%（避免抄底在半山腰）

### 5. 核心原则
- 空头市场宁可错过不可做错
- 持币观望是最优策略
- 若不确定，输出"观望"而非"买入"
"""

SIDEWAYS_MARKET_SKILL_POLICY_ZH = """## 震荡市场基线（必须严格遵守）

当前行情处于盘整/震荡，以下基线指导低吸高抛波段操作。

### 1. 箱体操作（支撑买阻力卖）
- 识别箱体顶部（阻力位）和底部（支撑位），只在箱底附近买入
- 距支撑位≤3%为买点区间，距阻力位≤3%为卖点区间
- 箱体中间1/3区域保持观望，不主动操作
- 箱体宽度<3%时不参与（操作空间不足）

### 2. 仓位管理（灵活）
- 箱底首仓3-4成，突破确认后加至5-6成
- 箱顶附近减至1-2成或清仓
- 严格在箱体内操作，不追突破（假突破概率高）

### 3. 量能辅助
- 箱底缩量企稳：支撑有效，可加重仓
- 箱顶放量滞涨：阻力有效，减仓信号
- 箱体突破（连续2日收盘站上或跌破+放量）：转为趋势策略

### 4. 风险控制
- 跌破箱体底部3%无条件止损
- 不参与无明显箱体结构的标的
- 震荡市中利好/利空消息易被放大，需结合技术面判断

### 5. 核心原则
- 不追高不杀跌，依托箱体边界操作
- 震荡市收益来自波段，耐心比判断更重要
"""


def _detect_regime_from_trend(trend_result: Optional[dict]) -> Optional[str]:
    """从 pipeline 预计算的 trend_result 推断 regime。

    用于在 agent 启动前确定应使用的基线策略，
    而非依赖 agent pipeline 内部的 SkillRouter 判断。
    
    返回: "trending_up" | "trending_down" | "sideways" | "volatile" | None
    """
    if not isinstance(trend_result, dict):
        return None
    ts = str(trend_result.get("trend_status", "")).lower()
    score = 0
    try:
        score = int(trend_result.get("signal_score", 50))
    except (TypeError, ValueError):
        pass
    vol = str(trend_result.get("volume_status", "")).lower()

    if any(k in ts for k in ("strong_bull", "bull")) and score >= 60:
        return "trending_up"
    if any(k in ts for k in ("bear", "strong_bear")) and score <= 40:
        return "trending_down"
    if any(k in ts for k in ("consolidation", "weak_bull", "weak_bear")):
        if "heavy" in vol:
            return "volatile"
        return "sideways"
    return None


def get_trading_skill_policy_by_regime(
    *,
    regime: Optional[str] = None,
    explicit_skill_selection: bool = False,
) -> str:
    """根据 regime（市场状态）返回最合适的基线策略。

    - trending_up → 默认牛市基线（CORE_TRADING_SKILL_POLICY_ZH）
    - trending_down → 空头基线（BEAR_MARKET_SKILL_POLICY_ZH）
    - sideways / volatile → 震荡基线（SIDEWAYS_MARKET_SKILL_POLICY_ZH）
    - None / 未知 → 默认牛市基线（向后兼容）
    - explicit_skill_selection=True → 空字符串（让技能自主判断）
    """
    if explicit_skill_selection:
        return ""

    if regime == "trending_down":
        return BEAR_MARKET_SKILL_POLICY_ZH
    if regime in ("sideways", "volatile"):
        return SIDEWAYS_MARKET_SKILL_POLICY_ZH
    return CORE_TRADING_SKILL_POLICY_ZH

TECHNICAL_SKILL_RULES_EN = """## Default Skill Baseline

Treat the currently activated skills as the primary analysis lens, but keep the
following default risk controls as the shared baseline:

- Bullish alignment: MA5 > MA10 > MA20
- Bias from MA5 < 2% -> ideal buy zone; 2-5% -> small position; > 5% -> no chase
- Shrink-pullback to MA5 is the preferred entry rhythm
- Below MA20 -> hold off unless the active skill explicitly proves a better setup
"""


def get_default_trading_skill_policy(*, explicit_skill_selection: bool) -> str:
    """Return the legacy default trading baseline only for implicit/default runs.

    When a caller explicitly chooses a skill (via request payload or config),
    analysis should follow that selected skill alone instead of silently
    layering the old bull-trend baseline on top.
    """
    if explicit_skill_selection:
        return ""
    return CORE_TRADING_SKILL_POLICY_ZH


def get_default_technical_skill_policy(*, explicit_skill_selection: bool) -> str:
    """Return the technical-agent baseline only for implicit/default runs."""
    if explicit_skill_selection:
        return ""
    return TECHNICAL_SKILL_RULES_EN


@lru_cache(maxsize=1)
def _load_builtin_skill_catalog() -> tuple[object, ...]:
    try:
        from src.agent.skills.base import load_skills_from_directory

        return tuple(load_skills_from_directory(_BUILTIN_SKILLS_DIR))
    except Exception:
        return ()


def _coerce_priority(value: object, default: int = 100) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_available_ids(available_skill_ids: Optional[Iterable[str]]) -> List[str]:
    normalized: List[str] = []
    if available_skill_ids is None:
        return normalized
    for skill_id in available_skill_ids:
        if isinstance(skill_id, str):
            cleaned = skill_id.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
    return normalized


def _normalize_skill_inputs(
    skills: Optional[Iterable[object]],
    available_skill_ids: Optional[Iterable[str]] = None,
) -> tuple[List[object], List[str]]:
    normalized_available = _normalize_available_ids(available_skill_ids)

    if skills is None:
        return list(_load_builtin_skill_catalog()), normalized_available

    skill_pool: List[object] = []
    for item in skills:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned and cleaned not in normalized_available:
                normalized_available.append(cleaned)
            continue
        if item is not None:
            skill_pool.append(item)
    return skill_pool, normalized_available


def _sort_skill_pool(skills: Iterable[object]) -> List[object]:
    return sorted(
        skills,
        key=lambda skill: (
            _coerce_priority(getattr(skill, "default_priority", 100)),
            str(getattr(skill, "display_name", "") or getattr(skill, "name", "")),
            str(getattr(skill, "name", "")),
        ),
    )


def _iter_candidate_skills(
    skills: Optional[Iterable[object]],
    *,
    available_skill_ids: Optional[Iterable[str]] = None,
    user_invocable_only: bool = True,
) -> tuple[List[object], List[str]]:
    skill_pool, normalized_available = _normalize_skill_inputs(skills, available_skill_ids)
    available_lookup = set(normalized_available)

    candidates: List[object] = []
    for skill in _sort_skill_pool(skill_pool):
        skill_id = str(getattr(skill, "name", "")).strip()
        if not skill_id:
            continue
        if user_invocable_only and not bool(getattr(skill, "user_invocable", True)):
            continue
        if available_lookup and skill_id not in available_lookup:
            continue
        candidates.append(skill)

    return candidates, normalized_available


def _slice_skill_ids(skill_ids: List[str], max_count: Optional[int]) -> List[str]:
    if max_count is None:
        return skill_ids
    return skill_ids[:max_count]


def _pick_primary_default_skill_id(candidates: List[object]) -> str:
    preferred = [
        str(getattr(skill, "name", "")).strip()
        for skill in candidates
        if bool(getattr(skill, "default_active", False))
    ]
    if preferred:
        return preferred[0]

    fallback = [str(getattr(skill, "name", "")).strip() for skill in candidates]
    if fallback:
        return fallback[0]

    return ""


def get_default_active_skill_ids(
    skills: Optional[Iterable[object]] = None,
    max_count: Optional[int] = None,
    available_skill_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    candidates, normalized_available = _iter_candidate_skills(
        skills,
        available_skill_ids=available_skill_ids,
    )
    default_skill_id = _pick_primary_default_skill_id(candidates)
    if default_skill_id:
        return _slice_skill_ids([default_skill_id], max_count)

    return _slice_skill_ids(normalized_available[:1], max_count)


def get_default_router_skill_ids(
    skills: Optional[Iterable[object]] = None,
    max_count: Optional[int] = None,
    available_skill_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    candidates, normalized_available = _iter_candidate_skills(
        skills,
        available_skill_ids=available_skill_ids,
    )
    preferred = [
        str(getattr(skill, "name", "")).strip()
        for skill in candidates
        if bool(getattr(skill, "default_router", False))
    ]
    if preferred:
        return _slice_skill_ids(preferred, max_count)

    return get_default_active_skill_ids(
        candidates,
        max_count=max_count,
        available_skill_ids=normalized_available,
    )


def get_regime_skill_ids(
    regime: str,
    skills: Optional[Iterable[object]] = None,
    max_count: Optional[int] = None,
    available_skill_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    candidates, normalized_available = _iter_candidate_skills(
        skills,
        available_skill_ids=available_skill_ids,
    )
    regime_name = (regime or "").strip().lower()
    if regime_name:
        matched = []
        for skill in candidates:
            market_regimes = getattr(skill, "market_regimes", None) or []
            normalized_regimes = {
                str(item).strip().lower()
                for item in market_regimes
                if str(item).strip()
            }
            if regime_name in normalized_regimes:
                matched.append(str(getattr(skill, "name", "")).strip())
        if matched:
            return _slice_skill_ids(matched, max_count)

    return get_default_router_skill_ids(
        candidates,
        max_count=max_count,
        available_skill_ids=normalized_available,
    )


def get_primary_default_skill_id(
    skills: Optional[Iterable[object]] = None,
    available_skill_ids: Optional[Iterable[str]] = None,
) -> str:
    defaults = get_default_active_skill_ids(skills, max_count=1, available_skill_ids=available_skill_ids)
    return defaults[0] if defaults else ""


def _build_regime_skill_ids(skills: Iterable[object]) -> Dict[str, List[str]]:
    regime_map: Dict[str, List[str]] = {}
    for skill in _sort_skill_pool(skills):
        skill_id = str(getattr(skill, "name", "")).strip()
        if not skill_id:
            continue
        for regime in getattr(skill, "market_regimes", None) or []:
            regime_name = str(regime).strip().lower()
            if not regime_name:
                continue
            regime_map.setdefault(regime_name, []).append(skill_id)
    return regime_map


DEFAULT_ACTIVE_SKILL_IDS: tuple[str, ...] = tuple(get_default_active_skill_ids())
DEFAULT_ROUTER_SKILL_IDS: tuple[str, ...] = tuple(get_default_router_skill_ids())
PRIMARY_DEFAULT_SKILL_ID = get_primary_default_skill_id()
REGIME_SKILL_IDS: Dict[str, List[str]] = _build_regime_skill_ids(_load_builtin_skill_catalog())


def build_skill_agent_name(skill_id: str) -> str:
    return f"{SKILL_AGENT_PREFIX}{skill_id}"


def extract_skill_id(agent_name: Optional[str]) -> Optional[str]:
    if not agent_name or not isinstance(agent_name, str):
        return None
    for prefix in (SKILL_AGENT_PREFIX, LEGACY_STRATEGY_AGENT_PREFIX):
        if agent_name.startswith(prefix):
            return agent_name[len(prefix):]
    return None


def is_skill_agent_name(agent_name: Optional[str]) -> bool:
    return extract_skill_id(agent_name) is not None


def is_skill_consensus_name(agent_name: Optional[str]) -> bool:
    return agent_name in {SKILL_CONSENSUS_AGENT_NAME, LEGACY_STRATEGY_CONSENSUS_AGENT_NAME}
