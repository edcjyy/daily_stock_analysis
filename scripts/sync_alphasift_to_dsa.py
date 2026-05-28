# -*- coding: utf-8 -*-
"""
AlphaSift → DSA 候选股同步脚本

功能：
1. 读取 AlphaSift 最近一次筛选的候选股（picks）
2. 更新 DSA 的 .env 中 STOCK_LIST 配置
3. 可选：为每只候选股创建止损/止盈告警规则

用法：
    # 手动执行
    python scripts/sync_alphasift_to_dsa.py

    # 指定 AlphaSift 数据目录
    python scripts/sync_alphasift_to_dsa.py --alphasift-data-dir /path/to/alphasift/data

    # 仅预览，不实际修改
    python scripts/sync_alphasift_to_dsa.py --dry-run

    # 定时执行（配合 crontab / Windows Task Scheduler）
    # 每天收盘后 16:00 执行
    # 0 16 * * 1-5 python /path/to/scripts/sync_alphasift_to_dsa.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 默认路径（可根据实际部署修改）
DEFAULT_ALPHASIFT_DATA_DIR = Path(r"E:\Proj\A\alphasift\data")
DEFAULT_DSA_ENV_PATH = Path(r"E:\Proj\A\daily_stock_analysis\.env")


def find_latest_alphasift_run(data_dir: Path) -> Optional[Dict[str, Any]]:
    """找到 AlphaSift 最近一次运行的结果文件并解析。"""
    runs_dir = data_dir / "runs"
    if not runs_dir.is_dir():
        logger.error("AlphaSift runs 目录不存在: %s", runs_dir)
        return None

    json_files = sorted(
        runs_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        logger.error("AlphaSift runs 目录为空: %s", runs_dir)
        return None

    latest = json_files[0]
    logger.info("读取 AlphaSift 最近运行: %s", latest.name)
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("解析 JSON 失败: %s", e)
        return None

    return data


def extract_picks(run_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从运行结果中提取候选股列表。

    Returns:
        [{"code": "603986", "name": "贵州茅台", "score": 85.5, ...}, ...]
    """
    picks = run_data.get("picks") or []
    if not picks:
        logger.warning("本次运行没有候选股")
    return picks


def picks_to_stock_list(picks: List[Dict[str, Any]], max_picks: int = 10) -> List[str]:
    """将 picks 转为股票代码列表，按 score 降序排列。"""
    # 按 score 降序
    sorted_picks = sorted(
        picks,
        key=lambda p: float(p.get("composite_score", p.get("score", 0)) or 0),
        reverse=True,
    )
    codes = []
    for pick in sorted_picks[:max_picks]:
        code = str(p.get("code") or p.get("stock_code", "")).strip()
        if code:
            codes.append(code)
    return codes


def update_dsa_env_stock_list(
    env_path: Path,
    new_codes: List[str],
    *,
    dry_run: bool = False,
) -> bool:
    """更新 DSA .env 文件中的 STOCK_LIST。"""
    if not env_path.is_file():
        logger.error("DSA .env 文件不存在: %s", env_path)
        return False

    content = env_path.read_text(encoding="utf-8")
    new_value = ",".join(new_codes)

    # 使用正则替换 STOCK_LIST=... 行
    pattern = re.compile(r"^(STOCK_LIST\s*=\s*).*$", re.MULTILINE)
    match = pattern.search(content)

    if match:
        old_value = match.group(0)
        new_line = f"STOCK_LIST={new_value}"
        if not dry_run:
            content = pattern.sub(new_line, content)
            env_path.write_text(content, encoding="utf-8")
        logger.info("STOCK_LIST: %s -> %s", old_value, new_line)
    else:
        # 如果不存在 STOCK_LIST，追加
        if not dry_run:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nSTOCK_LIST={new_value}\n")
        logger.info("追加 STOCK_LIST=%s", new_value)

    return True


def create_alert_rules_for_picks(
    picks: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """为候选股创建止损/止盈告警规则。

    注意：此功能需要 DSA 的 Python 环境和数据库，因此只在非 dry-run 模式下执行。
    """
    if dry_run:
        logger.info("[dry-run] 跳过告警规则创建")
        return []

    results = []
    try:
        # 临时将 DSA 加入 sys.path
        dsa_root = str(DEFAULT_DSA_ENV_PATH.parent)
        if dsa_root not in sys.path:
            sys.path.insert(0, dsa_root)

        from src.services.position_tracker import PositionTracker
        tracker = PositionTracker()

        for pick in picks:
            code = str(pick.get("code", "")).strip()
            name = str(pick.get("name", "")).strip()
            score = pick.get("composite_score", pick.get("score", 0))
            if not code:
                continue

            # 从 pick 数据中提取止损/止盈（如果有的话）
            stop_loss = pick.get("stop_loss")
            take_profit = pick.get("take_profit")

            if stop_loss and take_profit:
                try:
                    stop_loss_f = float(stop_loss)
                    take_profit_f = float(take_profit)
                    # 创建止损规则
                    tracker.alert_service.create_rule({
                        "name": f"[{code}] AlphaSift候选止损 @{stop_loss_f}",
                        "description": f"[AlphaSift] {name}({code}) 评分{score}，止损位 {stop_loss_f}",
                        "target_scope": "single_symbol",
                        "target": code,
                        "alert_type": "price_cross",
                        "severity": "critical",
                        "parameters": {"direction": "below", "price": stop_loss_f},
                        "enabled": True,
                        "source": "position_tracker",
                    })
                    # 创建止盈规则
                    tracker.alert_service.create_rule({
                        "name": f"[{code}] AlphaSift候选止盈 @{take_profit_f}",
                        "description": f"[AlphaSift] {name}({code}) 评分{score}，目标价 {take_profit_f}",
                        "target_scope": "single_symbol",
                        "target": code,
                        "alert_type": "price_cross",
                        "severity": "warning",
                        "parameters": {"direction": "above", "price": take_profit_f},
                        "enabled": True,
                        "source": "position_tracker",
                    })
                    results.append({"code": code, "name": name, "status": "rules_created"})
                except Exception as e:
                    results.append({"code": code, "name": name, "status": "error", "error": str(e)})
            else:
                results.append({"code": code, "name": name, "status": "no_price_levels"})

    except ImportError as e:
        logger.warning("无法导入 DSA 模块（告警规则创建跳过）: %s", e)
        for pick in picks:
            code = str(pick.get("code", "")).strip()
            name = str(pick.get("name", "")).strip()
            results.append({"code": code, "name": name, "status": "import_error"})

    return results


def main():
    parser = argparse.ArgumentParser(description="AlphaSift → DSA 候选股同步")
    parser.add_argument(
        "--alphasift-data-dir",
        type=Path,
        default=DEFAULT_ALPHASIFT_DATA_DIR,
        help=f"AlphaSift 数据目录 (默认: {DEFAULT_ALPHASIFT_DATA_DIR})",
    )
    parser.add_argument(
        "--dsa-env-path",
        type=Path,
        default=DEFAULT_DSA_ENV_PATH,
        help=f"DSA .env 文件路径 (默认: {DEFAULT_DSA_ENV_PATH})",
    )
    parser.add_argument(
        "--max-picks",
        type=int,
        default=10,
        help="最大同步候选数量 (默认: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际修改文件",
    )
    parser.add_argument(
        "--create-alerts",
        action="store_true",
        help="同时为候选股创建告警规则（需要 DSA 环境）",
    )
    args = parser.parse_args()

    logger.info("=== AlphaSift → DSA 同步开始 ===")
    if args.dry_run:
        logger.info("[DRY RUN] 不会修改任何文件")

    # 1. 读取 AlphaSift 最近运行结果
    run_data = find_latest_alphasift_run(args.alphasift_data_dir)
    if run_data is None:
        logger.error("无法读取 AlphaSift 运行结果，退出")
        sys.exit(1)

    run_id = run_data.get("run_id", "unknown")
    strategy = run_data.get("strategy", "unknown")
    created_at = run_data.get("created_at", "unknown")
    logger.info("运行信息: run_id=%s, strategy=%s, created_at=%s", run_id, strategy, created_at)

    # 2. 提取候选股
    picks = extract_picks(run_data)
    if not picks:
        logger.warning("没有候选股可同步")
        sys.exit(0)

    codes = picks_to_stock_list(picks, max_picks=args.max_picks)
    logger.info("候选股 (%d/%d): %s", len(codes), len(picks), ", ".join(codes))

    # 打印候选详情
    for pick in picks[:args.max_picks]:
        code = pick.get("code", "?")
        name = pick.get("name", "?")
        score = pick.get("composite_score", pick.get("score", 0))
        logger.info("  %s %s 评分=%.1f", code, name, score)

    # 3. 更新 DSA STOCK_LIST
    success = update_dsa_env_stock_list(
        args.dsa_env_path,
        codes,
        dry_run=args.dry_run,
    )
    if success:
        logger.info("STOCK_LIST 更新完成")
    else:
        logger.error("STOCK_LIST 更新失败")
        sys.exit(1)

    # 4. 可选：创建告警规则
    if args.create_alerts:
        alert_results = create_alert_rules_for_picks(
            picks[:args.max_picks],
            dry_run=args.dry_run,
        )
        for r in alert_results:
            if r.get("status") == "rules_created":
                logger.info("  %s (%s): 告警规则已创建", r["code"], r["name"])
            else:
                logger.warning("  %s (%s): %s", r["code"], r.get("name", "?"), r.get("status"))

    logger.info("=== 同步完成 ===")


if __name__ == "__main__":
    main()
