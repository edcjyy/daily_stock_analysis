# -*- coding: utf-8 -*-
"""
PositionTracker — 持仓动态跟踪 & 止损自动管理

核心职责：
1. 从分析报告的 sniper_points 自动创建/更新止损告警规则（price_cross）
2. 动态 trailing stop：股价上涨时自动上移止损位
3. 独立脚本可手动/定时执行，也可在 pipeline 分析完成后自动触发

集成点：
- AlertService.create_rule / update_rule → 创建和更新告警规则
- AlertRepository.list_rules → 查找已有规则
- orchestrator 的 dashboard sniper_points → 止损/止盈价位
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 告警来源标识，用于区分手动创建和自动同步的规则
SOURCE_TAG = "position_tracker"

# 止损告警的描述模板
STOP_LOSS_DESC = "[自动跟踪] 跌破分析止损位 {price}"
TAKE_PROFIT_DESC = "[自动跟踪] 触及分析目标价 {price}"
TRAILING_UPDATED_DESC = "[动态止损] 已从 {old_price} 上移至 {new_price}"


class PositionTracker:
    """持仓动态跟踪器 — 将 sniper_points 同步为 Alert 规则 + trailing stop."""

    def __init__(self, alert_service=None):
        """
        Args:
            alert_service: AlertService 实例，为 None 时延迟初始化。
        """
        self._alert_svc = alert_service

    @property
    def alert_service(self):
        if self._alert_svc is None:
            from src.services.alert_service import AlertService
            self._alert_svc = AlertService()
        return self._alert_svc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_from_dashboard(
        self,
        stock_code: str,
        dashboard: Dict[str, Any],
        *,
        trailing_method: str = "breakeven",
        trailing_trigger_pct: float = 50.0,
    ) -> Dict[str, Any]:
        """从 orchestrator 输出的 dashboard 同步止损/止盈告警规则。

        在 orchestrator 分析完成后调用此方法，自动将 sniper_points
        中的 stop_loss / take_profit 创建为 AlertService 的 price_cross 规则。

        Args:
            stock_code: 股票代码（如 "603986"）
            dashboard: orchestrator 的 _normalize_dashboard_payload 输出
            trailing_method: 追踪止损方法
                - "breakeven": 利润超过 trailing_trigger_pct% 时，止损移到成本价
                - "fixed_pct": 止损固定在买入价下方 trailing_trigger_pct%
                - "none": 不做 trailing，仅静态止损
            trailing_trigger_pct: 触发 trailing 的涨幅百分比（默认 50%）

        Returns:
            操作结果摘要 dict:
            {
                "stock_code": str,
                "stop_loss_rule": {"action": "created"|"updated"|"skipped", "rule_id": int|None},
                "take_profit_rule": {"action": "created"|"updated"|"skipped", "rule_id": int|None},
                "trailing_stop_applied": bool,
            }
        """
        result: Dict[str, Any] = {
            "stock_code": stock_code,
            "stop_loss_rule": {"action": "skipped", "rule_id": None},
            "take_profit_rule": {"action": "skipped", "rule_id": None},
            "trailing_stop_applied": False,
        }

        # 提取 sniper_points — 兼容两种结构：
        #   1) pipeline 传入的是内层 dashboard（已含 battle_plan）
        #   2) orchestrator 传入的是外层（内含 .dashboard 子键）
        inner = dashboard
        if "dashboard" in dashboard and isinstance(dashboard["dashboard"], dict):
            inner = dashboard["dashboard"]
        battle_plan = inner.get("battle_plan") or {}
        sniper = battle_plan.get("sniper_points") or {}
        decision_type = inner.get("decision_type") or dashboard.get("decision_type") or "hold"

        stop_loss = self._coerce_price(sniper.get("stop_loss"))
        take_profit = self._coerce_price(sniper.get("take_profit"))
        ideal_buy = self._coerce_price(sniper.get("ideal_buy"))

        # --- 止损规则 ---
        if stop_loss and stop_loss > 0:
            result["stop_loss_rule"] = self._upsert_price_cross_rule(
                stock_code=stock_code,
                direction="below",
                price=stop_loss,
                name=f"[{stock_code}] 止损 @ {stop_loss}",
                description=STOP_LOSS_DESC.format(price=stop_loss),
            )
            logger.info(
                "[PositionTracker] %s 止损规则 %s: price=%.2f",
                stock_code, result["stop_loss_rule"]["action"], stop_loss,
            )

        # --- 止盈规则 ---
        if take_profit and take_profit > 0:
            result["take_profit_rule"] = self._upsert_price_cross_rule(
                stock_code=stock_code,
                direction="above",
                price=take_profit,
                name=f"[{stock_code}] 止盈 @ {take_profit}",
                description=TAKE_PROFIT_DESC.format(price=take_profit),
            )
            logger.info(
                "[PositionTracker] %s 止盈规则 %s: price=%.2f",
                stock_code, result["take_profit_rule"]["action"], take_profit,
            )

        # --- Trailing stop ---
        if trailing_method != "none" and ideal_buy and stop_loss and ideal_buy > 0:
            # 将 trailing 信息存储在规则描述中，供后续 update_trailing_stops 使用
            result["trailing_stop_applied"] = True
            result["_meta"] = {
                "ideal_buy": ideal_buy,
                "stop_loss": stop_loss,
                "trailing_method": trailing_method,
                "trailing_trigger_pct": trailing_trigger_pct,
            }

        return result

    def update_trailing_stops(
        self,
        realtime_quotes: Dict[str, float],
        *,
        trailing_method: str = "breakeven",
        trailing_trigger_pct: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """遍历所有 position_tracker 来源的止损规则，根据最新价格上移止损位。

        Args:
            realtime_quotes: {stock_code: current_price} 实时价格字典
            trailing_method: 追踪止损方法（同 sync_from_dashboard）
            trailing_trigger_pct: 触发 trailing 的涨幅百分比

        Returns:
            更新的规则列表，每项包含 {stock_code, old_stop, new_stop, rule_id}
        """
        updated = []

        # 找到所有 position_tracker 来源的止损规则
        rules = self._find_tracker_rules(alert_type="price_cross")
        for rule in rules:
            try:
                params = json.loads(rule.get("parameters") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue

            if params.get("direction") != "below":
                continue

            target = rule.get("target", "")
            old_stop = params.get("price", 0)
            if not target or old_stop <= 0:
                continue

            current = realtime_quotes.get(target)
            if current is None or current <= 0:
                continue

            # 检查是否需要从描述中提取 ideal_buy
            ideal_buy = self._extract_ideal_buy_from_rule(rule)
            new_stop = self._calculate_trailing_stop(
                ideal_buy=ideal_buy,
                old_stop=old_stop,
                current_price=current,
                method=trailing_method,
                trigger_pct=trailing_trigger_pct,
            )

            if new_stop is None or new_stop <= old_stop:
                # 不需要上移或无法计算
                continue

            # 更新规则
            new_params = dict(params, price=new_stop)
            desc = TRAILING_UPDATED_DESC.format(
                old_price=old_stop, new_price=new_stop
            )
            self.alert_service.update_rule(rule["id"], {
                "parameters": json.dumps(new_params, ensure_ascii=False),
                "description": desc,
                "updated_at": datetime.now(),
            })
            logger.info(
                "[PositionTracker] %s trailing stop: %.2f -> %.2f",
                target, old_stop, new_stop,
            )
            updated.append({
                "stock_code": target,
                "old_stop": old_stop,
                "new_stop": new_stop,
                "rule_id": rule["id"],
            })

        return updated

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_price_cross_rule(
        self,
        stock_code: str,
        direction: str,
        price: float,
        name: str,
        description: str,
    ) -> Dict[str, Any]:
        """创建或更新一条 price_cross 告警规则。

        使用 source=position_tracker + target=stock_code + alert_type=price_cross
        + direction 作为唯一键，已存在则更新价格。
        """
        # 查找已有规则
        existing = self._find_tracker_rules(
            alert_type="price_cross",
            target=stock_code,
        )
        # 按 direction 筛选
        for rule in existing:
            try:
                params = json.loads(rule.get("parameters") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if params.get("direction") == direction:
                # 更新已有规则
                new_params = dict(params, price=price)
                self.alert_service.update_rule(rule["id"], {
                    "parameters": json.dumps(new_params, ensure_ascii=False),
                    "description": description,
                    "name": name,
                    "updated_at": datetime.now(),
                })
                return {"action": "updated", "rule_id": rule["id"]}

        # 创建新规则
        try:
            created = self.alert_service.create_rule({
                "name": name,
                "description": description,
                "target_scope": "single_symbol",
                "target": stock_code,
                "alert_type": "price_cross",
                "severity": "critical" if direction == "below" else "warning",
                "parameters": {
                    "direction": direction,
                    "price": price,
                },
                "enabled": True,
                "source": SOURCE_TAG,
            })
            return {"action": "created", "rule_id": created.get("id")}
        except Exception as e:
            logger.warning("[PositionTracker] 创建规则失败 %s: %s", stock_code, e)
            return {"action": "error", "rule_id": None, "error": str(e)}

    def _find_tracker_rules(
        self,
        alert_type: Optional[str] = None,
        target: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查找 source=position_tracker 的规则。"""
        from src.repositories.alert_repo import AlertRepository

        repo = AlertRepository()
        rows, _ = repo.list_rules(
            source=SOURCE_TAG,
            alert_type=alert_type,
            target=target,
            page=1,
            page_size=200,
        )
        # 序列化为 dict
        from sqlalchemy import inspect
        result = []
        for row in rows:
            d = {}
            for col in inspect(row).mapper.column_attrs:
                d[col.key] = getattr(row, col.key)
            result.append(d)
        return result

    @staticmethod
    def _coerce_price(value: Any) -> Optional[float]:
        """将各种类型的价位值转为 float，无效则返回 None。

        支持格式：
        - 数字: 35.5, 36
        - 纯数字字符串: "35.5"
        - 带说明的字符串: "35.5（跌破筹码密集区下沿止损）"
        - 范围字符串: "39.5-40.0（MA20阻力位附近）" → 取下限（第一个数字）
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip().replace(",", "")
            if s in ("N/A", "待补充", "", "null", "None"):
                return None
            try:
                return float(s)
            except ValueError:
                pass
            # 尝试从 "35.5（说明）" 或 "39.5-40.0（说明）" 提取第一个数字
            m = re.search(r"(\d+\.?\d*)", s)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
            return None
        return None

    @staticmethod
    def _extract_ideal_buy_from_rule(rule: Dict[str, Any]) -> Optional[float]:
        """尝试从规则描述或关联数据中提取 ideal_buy 价格。"""
        # 暂时无法从规则自身获取 ideal_buy（AlertService 不存储额外 meta）
        # 后续可考虑扩展 alert rules 表增加 meta JSON 字段
        return None

    @staticmethod
    def _calculate_trailing_stop(
        ideal_buy: Optional[float],
        old_stop: float,
        current_price: float,
        method: str,
        trigger_pct: float,
    ) -> Optional[float]:
        """计算新的 trailing stop 价格。返回 None 表示不需要调整。

        Args:
            ideal_buy: 建议买入价（可能为 None）
            old_stop: 当前止损价
            current_price: 当前市场价格
            method: "breakeven" | "fixed_pct"
            trigger_pct: 触发 trailing 的涨幅百分比
        """
        if ideal_buy is not None and ideal_buy > 0:
            gain_pct = (current_price - ideal_buy) / ideal_buy * 100
        else:
            # 无 ideal_buy 时用 old_stop 作为参考成本
            gain_pct = (current_price - old_stop) / old_stop * 100

        if gain_pct < trigger_pct:
            return None  # 涨幅不够，不动止损

        if method == "breakeven" and ideal_buy and ideal_buy > 0:
            # 保本止损：移到成本价（加一点缓冲 0.5%）
            new_stop = ideal_buy * 0.995
        elif method == "fixed_pct" and ideal_buy and ideal_buy > 0:
            # 固定百分比止损：始终在成本下方 trigger_pct/2 处
            new_stop = ideal_buy * (1 - trigger_pct / 200)
        else:
            # 兜底：新止损不低于当前价和旧止损的中点
            new_stop = old_stop + (current_price - old_stop) * 0.5

        # 止损只能上移，不能下移
        if new_stop <= old_stop:
            return None

        return round(new_stop, 2)


# ------------------------------------------------------------------
# Convenience: 供 orchestrator 调用的顶层函数
# ------------------------------------------------------------------

def sync_stop_loss_from_dashboard(
    stock_code: str,
    dashboard: Dict[str, Any],
) -> Dict[str, Any]:
    """分析完成后自动同步止损规则（orchestrator 集成点）。

    Usage in orchestrator._execute_pipeline:
        from src.services.position_tracker import sync_stop_loss_from_dashboard
        sync_stop_loss_from_dashboard(ctx.stock_code, dashboard)
    """
    from src.config import get_config

    config = get_config()
    enabled = getattr(config, "position_tracker_enabled", True)
    if not enabled:
        return {"action": "disabled", "stock_code": stock_code}

    method = getattr(config, "trailing_stop_method", "breakeven")
    trigger_pct = float(getattr(config, "trailing_stop_trigger_pct", 50.0))

    tracker = PositionTracker()
    return tracker.sync_from_dashboard(
        stock_code, dashboard,
        trailing_method=method,
        trailing_trigger_pct=trigger_pct,
    )
