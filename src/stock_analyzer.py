# -*- coding: utf-8 -*-
"""
===================================
趋势交易分析器 - 基于用户交易理念
===================================

交易理念核心原则：
1. 严进策略 - 不追高，追求每笔交易成功率
2. 趋势交易 - MA5>MA10>MA20 多头排列，顺势而为
3. 效率优先 - 关注筹码结构好的股票
4. 买点偏好 - 在 MA5/MA10 附近回踩买入

技术标准：
- 多头排列：MA5 > MA10 > MA20
- 乖离率：(Close - MA5) / MA5 < 5%（不追高）
- 量能形态：缩量回调优先
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List
from enum import Enum

import pandas as pd
import numpy as np

from src.config import get_config

logger = logging.getLogger(__name__)


class TrendStatus(Enum):
    """趋势状态枚举"""
    STRONG_BULL = "强势多头"      # MA5 > MA10 > MA20，且间距扩大
    BULL = "多头排列"             # MA5 > MA10 > MA20
    WEAK_BULL = "弱势多头"        # MA5 > MA10，但 MA10 < MA20
    CONSOLIDATION = "盘整"        # 均线缠绕
    WEAK_BEAR = "弱势空头"        # MA5 < MA10，但 MA10 > MA20
    BEAR = "空头排列"             # MA5 < MA10 < MA20
    STRONG_BEAR = "强势空头"      # MA5 < MA10 < MA20，且间距扩大


class VolumeStatus(Enum):
    """量能状态枚举"""
    HEAVY_VOLUME_UP = "放量上涨"       # 量价齐升
    HEAVY_VOLUME_DOWN = "放量下跌"     # 放量杀跌
    SHRINK_VOLUME_UP = "缩量上涨"      # 无量上涨
    SHRINK_VOLUME_DOWN = "缩量回调"    # 缩量回调（好）
    NORMAL = "量能正常"


class BuySignal(Enum):
    """买入信号枚举"""
    STRONG_BUY = "强烈买入"       # 多条件满足
    BUY = "买入"                  # 基本条件满足
    HOLD = "持有"                 # 已持有可继续
    WAIT = "观望"                 # 等待更好时机
    SELL = "卖出"                 # 趋势转弱
    STRONG_SELL = "强烈卖出"      # 趋势破坏


class MACDStatus(Enum):
    """MACD状态枚举"""
    GOLDEN_CROSS_ZERO = "零轴上金叉"      # DIF上穿DEA，且在零轴上方
    GOLDEN_CROSS = "金叉"                # DIF上穿DEA
    BULLISH = "多头"                    # DIF>DEA>0
    CROSSING_UP = "上穿零轴"             # DIF上穿零轴
    CROSSING_DOWN = "下穿零轴"           # DIF下穿零轴
    BEARISH = "空头"                    # DIF<DEA<0
    DEATH_CROSS = "死叉"                # DIF下穿DEA


class RSIStatus(Enum):
    """RSI状态枚举"""
    OVERBOUGHT = "超买"        # RSI > 70
    STRONG_BUY = "强势买入"    # 50 < RSI < 70
    NEUTRAL = "中性"          # 40 <= RSI <= 60
    WEAK = "弱势"             # 30 < RSI < 40
    OVERSOLD = "超卖"         # RSI < 30


@dataclass
class TrendAnalysisResult:
    """趋势分析结果"""
    code: str
    
    # 趋势判断
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    ma_alignment: str = ""           # 均线排列描述
    trend_strength: float = 0.0      # 趋势强度 0-100
    
    # 均线数据
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    current_price: float = 0.0
    
    # 乖离率（与 MA5 的偏离度）
    bias_ma5: float = 0.0            # (Close - MA5) / MA5 * 100
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    
    # 量能分析
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    volume_ratio_5d: float = 0.0     # 当日成交量/5日均量
    volume_trend: str = ""           # 量能趋势描述
    
    # 支撑压力
    support_ma5: bool = False        # MA5 是否构成支撑
    support_ma10: bool = False       # MA10 是否构成支撑
    resistance_levels: List[float] = field(default_factory=list)
    support_levels: List[float] = field(default_factory=list)

    # MACD 指标
    macd_dif: float = 0.0          # DIF 快线
    macd_dea: float = 0.0          # DEA 慢线
    macd_bar: float = 0.0           # MACD 柱状图
    macd_status: MACDStatus = MACDStatus.BULLISH
    macd_signal: str = ""            # MACD 信号描述

    # RSI 指标
    rsi_6: float = 0.0              # RSI(6) 短期
    rsi_12: float = 0.0             # RSI(12) 中期
    rsi_24: float = 0.0             # RSI(24) 长期
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    rsi_signal: str = ""              # RSI 信号描述

    # 买入信号
    buy_signal: BuySignal = BuySignal.WAIT
    signal_score: int = 0            # 综合评分 0-100
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    # ── 新增因子 ──
    # 多周期动量
    change_5d: float = 0.0
    change_20d: float = 0.0
    change_60d: float = 0.0
    # 日内K线结构
    body_pct: float = 0.0            # 实体幅度 (|close-open|/open)
    upper_shadow_pct: float = 0.0    # 上影线比例
    lower_shadow_pct: float = 0.0    # 下影线比例
    is_bullish_candle: bool = False  # 是否阳线
    # 外部数据(由 Pipeline 注入)
    chip_profit_ratio: float = 0.0   # 筹码获利比例
    chip_concentration: float = 0.0  # 筹码集中度(90%)
    main_net_inflow_5d: float = 0.0  # 主力5日净流入
    pe_ratio: float = 0.0            # PE
    pb_ratio: float = 0.0            # PB
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'trend_status': self.trend_status.value,
            'ma_alignment': self.ma_alignment,
            'trend_strength': self.trend_strength,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'current_price': self.current_price,
            'bias_ma5': self.bias_ma5,
            'bias_ma10': self.bias_ma10,
            'bias_ma20': self.bias_ma20,
            'volume_status': self.volume_status.value,
            'volume_ratio_5d': self.volume_ratio_5d,
            'volume_trend': self.volume_trend,
            'support_ma5': self.support_ma5,
            'support_ma10': self.support_ma10,
            'support_levels': self.support_levels,
            'resistance_levels': self.resistance_levels,
            'buy_signal': self.buy_signal.value,
            'signal_score': self.signal_score,
            'signal_reasons': self.signal_reasons,
            'risk_factors': self.risk_factors,
            'change_5d': self.change_5d,
            'change_20d': self.change_20d,
            'change_60d': self.change_60d,
            'body_pct': self.body_pct,
            'chip_profit_ratio': self.chip_profit_ratio,
            'main_net_inflow_5d': self.main_net_inflow_5d,
            'pe_ratio': self.pe_ratio,
            'pb_ratio': self.pb_ratio,
            'macd_dif': self.macd_dif,
            'macd_dea': self.macd_dea,
            'macd_bar': self.macd_bar,
            'macd_status': self.macd_status.value,
            'macd_signal': self.macd_signal,
            'rsi_6': self.rsi_6,
            'rsi_12': self.rsi_12,
            'rsi_24': self.rsi_24,
            'rsi_status': self.rsi_status.value,
            'rsi_signal': self.rsi_signal,
        }


def _pct_change(df: pd.DataFrame, window: int) -> float:
    """Calculate percentage change over window days from close prices."""
    if df is None or df.empty or len(df) < window + 1:
        return 0.0
    try:
        close_series = pd.to_numeric(df['close'], errors='coerce').dropna()
        if len(close_series) < window + 1:
            return 0.0
        return float((close_series.iloc[-1] / close_series.iloc[-window-1] - 1) * 100)
    except Exception:
        return 0.0


def _validate_result_sanity(result: TrendAnalysisResult, code: str) -> None:
    """Check computed metrics for implausible values (stale data, DB corruption)."""
    warnings = []
    if result.current_price <= 0:
        warnings.append(f"current_price={result.current_price}")
    if result.ma5 <= 0 and result.ma20 > 0:
        warnings.append(f"MA5={result.ma5} but MA20={result.ma20} (inconsistent)")
    if not (0 <= result.rsi_12 <= 100) and result.rsi_12 != 0:
        warnings.append(f"RSI12={result.rsi_12} (out of 0-100)")
    if result.signal_score < 0 or result.signal_score > 100:
        warnings.append(f"signal_score={result.signal_score} (expected 0-100)")
    if abs(result.bias_ma5) > 15:
        warnings.append(f"bias_ma5={result.bias_ma5}% (extreme, possible data error)")
    if result.ma10 > 0 and result.current_price > result.ma10 * 1.5:
        warnings.append(f"price/MA10 ratio > 1.5x")

    if warnings:
        logger.warning("[Sanity] %s implausible metrics: %s", code, "; ".join(warnings))


class StockTrendAnalyzer:
    """
    股票趋势分析器

    基于用户交易理念实现：
    1. 趋势判断 - MA5>MA10>MA20 多头排列
    2. 乖离率检测 - 不追高，偏离 MA5 超过 5% 不买
    3. 量能分析 - 偏好缩量回调
    4. 买点识别 - 回踩 MA5/MA10 支撑
    5. MACD 指标 - 趋势确认和金叉死叉信号
    6. RSI 指标 - 超买超卖判断
    """
    
    # 交易参数配置（BIAS_THRESHOLD 从 Config 读取，见 _generate_signal）
    VOLUME_SHRINK_RATIO = 0.7   # 缩量判断阈值（当日量/5日均量）
    VOLUME_HEAVY_RATIO = 1.5    # 放量判断阈值
    MA_SUPPORT_TOLERANCE = 0.02  # MA 支撑判断容忍度（2%）

    # MACD 参数（标准12/26/9）
    MACD_FAST = 12              # 快线周期
    MACD_SLOW = 26             # 慢线周期
    MACD_SIGNAL = 9             # 信号线周期

    # RSI 参数
    RSI_SHORT = 6               # 短期RSI周期
    RSI_MID = 12               # 中期RSI周期
    RSI_LONG = 24              # 长期RSI周期
    RSI_OVERBOUGHT = 70        # 超买阈值
    RSI_OVERSOLD = 30          # 超卖阈值
    
    def __init__(self):
        """初始化分析器"""
        pass
    
    def analyze(
        self, df: pd.DataFrame, code: str,
        chip_data: dict = None,
        capital_flow: dict = None,
        fundamental: dict = None,
    ) -> TrendAnalysisResult:
        """
        分析股票趋势
        
        Args:
            df: 包含 OHLCV 数据的 DataFrame
            code: 股票代码
            chip_data: 可选, 筹码分布 {'profit_ratio': 58.2, 'concentration_90': 8.29}
            capital_flow: 可选, 资金流向 {'main_net_inflow_5d': -8335}
            fundamental: 可选, 基本面 {'pe_ratio': 11.86, 'pb_ratio': 1.173}
            
        Returns:
            TrendAnalysisResult 分析结果
        """
        result = TrendAnalysisResult(code=code)
        
        if df is None or df.empty or len(df) < 20:
            logger.warning(f"{code} 数据不足，无法进行趋势分析")
            result.risk_factors.append("数据不足，无法完成分析")
            return result
        
        # 确保数据按日期排序
        df = df.sort_values('date').reset_index(drop=True)
        
        # 计算均线
        df = self._calculate_mas(df)

        # 计算 MACD 和 RSI
        df = self._calculate_macd(df)
        df = self._calculate_rsi(df)

        # 获取最新数据
        latest = df.iloc[-1]
        result.current_price = float(latest['close'])
        result.ma5 = float(latest['MA5'])
        result.ma10 = float(latest['MA10'])
        result.ma20 = float(latest['MA20'])
        result.ma60 = float(latest.get('MA60', 0))

        # 1. 趋势判断
        self._analyze_trend(df, result)

        # 2. 乖离率计算
        self._calculate_bias(result)

        # 3. 量能分析
        self._analyze_volume(df, result)

        # 4. 支撑压力分析
        self._analyze_support_resistance(df, result)

        # 5. MACD 分析
        self._analyze_macd(df, result)

        # 6. RSI 分析
        self._analyze_rsi(df, result)

        # ── 7. 新因子: 数据注入（必须在评分前）──

        # 7a. 多周期动量
        result.change_5d = float(_pct_change(df, 5))
        result.change_20d = float(_pct_change(df, 20))
        result.change_60d = float(_pct_change(df, 60))

        # 7b. 日内K线结构
        latest = df.iloc[-1]
        o, h, l, c = float(latest['open']), float(latest['high']), float(latest['low']), float(latest['close'])
        body = abs(c - o) / o if o > 0 else 0
        result.body_pct = round(body * 100, 2)
        result.upper_shadow_pct = round((h - max(c, o)) / o * 100, 2) if o > 0 else 0
        result.lower_shadow_pct = round((min(c, o) - l) / o * 100, 2) if o > 0 else 0
        result.is_bullish_candle = c > o

        # 7c. 外部数据（筹码、资金流、估值）
        if chip_data:
            result.chip_profit_ratio = float(chip_data.get('profit_ratio', 0))
            try:
                result.chip_concentration = float(chip_data.get('concentration_90', chip_data.get('concentration', 0)))
            except (TypeError, ValueError):
                pass
        if capital_flow:
            result.main_net_inflow_5d = float(capital_flow.get('main_net_inflow', 0) or 0)
        if fundamental:
            val = fundamental.get('valuation', {})
            val_data = val.get('data', val) if isinstance(val, dict) else {}
            result.pe_ratio = float(val_data.get('pe_ratio', 0) or 0)
            result.pb_ratio = float(val_data.get('pb_ratio', 0) or 0)

        # ── 8. 生成买入信号（在所有数据注入之后）──
        self._generate_signal(result)

        logger.info(
            "[TrendAnalyzer] %s external: chip=%.1f%% conc=%.1f%% flow=%.0f PE=%.1f PB=%.2f",
            code,
            result.chip_profit_ratio, result.chip_concentration,
            result.main_net_inflow_5d, result.pe_ratio, result.pb_ratio,
        )

        # POST: validate key metrics for sanity
        _validate_result_sanity(result, code)

        return result
    
    def _calculate_mas(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算均线"""
        df = df.copy()
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        if len(df) >= 60:
            df['MA60'] = df['close'].rolling(window=60).mean()
        else:
            df['MA60'] = df['MA20']  # 数据不足时使用 MA20 替代
        return df

    def _calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 MACD 指标

        公式：
        - EMA(12)：12日指数移动平均
        - EMA(26)：26日指数移动平均
        - DIF = EMA(12) - EMA(26)
        - DEA = EMA(DIF, 9)
        - MACD = (DIF - DEA) * 2
        """
        df = df.copy()

        # 计算快慢线 EMA
        ema_fast = df['close'].ewm(span=self.MACD_FAST, adjust=False).mean()
        ema_slow = df['close'].ewm(span=self.MACD_SLOW, adjust=False).mean()

        # 计算快线 DIF
        df['MACD_DIF'] = ema_fast - ema_slow

        # 计算信号线 DEA
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=self.MACD_SIGNAL, adjust=False).mean()

        # 计算柱状图
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2

        return df

    def _calculate_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 RSI 指标（Wilder's EMA / SMMA 口径）

        公式：
        - avg_gain / avg_loss 使用 ewm(alpha=1/period, adjust=False)
        - RS = avg_gain / avg_loss
        - RSI = 100 - (100 / (1 + RS))
        """
        df = df.copy()

        for period in [self.RSI_SHORT, self.RSI_MID, self.RSI_LONG]:
            # 计算价格变化
            delta = df['close'].diff()

            # 分离上涨和下跌
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            # 使用 Wilder's EMA / SMMA 口径，与常见 RSI 图表工具保持一致。
            avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

            # 计算 RS 和 RSI
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            # 填充 NaN 值
            rsi = rsi.fillna(50)  # 默认中性值

            # 添加到 DataFrame
            col_name = f'RSI_{period}'
            df[col_name] = rsi

        return df
    
    def _analyze_trend(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析趋势状态
        
        核心逻辑：判断均线排列和趋势强度
        """
        ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
        
        # 判断均线排列
        if ma5 > ma10 > ma20:
            # 检查间距是否在扩大（强势）
            prev = df.iloc[-5] if len(df) >= 5 else df.iloc[-1]
            prev_spread = (prev['MA5'] - prev['MA20']) / prev['MA20'] * 100 if prev['MA20'] > 0 else 0
            curr_spread = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0
            
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BULL
                result.ma_alignment = "强势多头排列，均线发散上行"
                result.trend_strength = 90
            else:
                result.trend_status = TrendStatus.BULL
                result.ma_alignment = "多头排列 MA5>MA10>MA20"
                result.trend_strength = 75
                
        elif ma5 > ma10 and ma10 <= ma20:
            result.trend_status = TrendStatus.WEAK_BULL
            result.ma_alignment = "弱势多头，MA5>MA10 但 MA10≤MA20"
            result.trend_strength = 55
            
        elif ma5 < ma10 < ma20:
            prev = df.iloc[-5] if len(df) >= 5 else df.iloc[-1]
            prev_spread = (prev['MA20'] - prev['MA5']) / prev['MA5'] * 100 if prev['MA5'] > 0 else 0
            curr_spread = (ma20 - ma5) / ma5 * 100 if ma5 > 0 else 0
            
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BEAR
                result.ma_alignment = "强势空头排列，均线发散下行"
                result.trend_strength = 10
            else:
                result.trend_status = TrendStatus.BEAR
                result.ma_alignment = "空头排列 MA5<MA10<MA20"
                result.trend_strength = 25
                
        elif ma5 < ma10 and ma10 >= ma20:
            result.trend_status = TrendStatus.WEAK_BEAR
            result.ma_alignment = "弱势空头，MA5<MA10 但 MA10≥MA20"
            result.trend_strength = 40
            
        else:
            result.trend_status = TrendStatus.CONSOLIDATION
            result.ma_alignment = "均线缠绕，趋势不明"
            result.trend_strength = 50
    
    def _calculate_bias(self, result: TrendAnalysisResult) -> None:
        """
        计算乖离率
        
        乖离率 = (现价 - 均线) / 均线 * 100%
        
        严进策略：乖离率超过 5% 不追高
        """
        price = result.current_price
        
        if result.ma5 > 0:
            result.bias_ma5 = (price - result.ma5) / result.ma5 * 100
        if result.ma10 > 0:
            result.bias_ma10 = (price - result.ma10) / result.ma10 * 100
        if result.ma20 > 0:
            result.bias_ma20 = (price - result.ma20) / result.ma20 * 100
    
    def _analyze_volume(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析量能
        
        偏好：缩量回调 > 放量上涨 > 缩量上涨 > 放量下跌
        """
        if len(df) < 5:
            return
        
        latest = df.iloc[-1]
        vol_5d_avg = df['volume'].iloc[-6:-1].mean()
        
        if vol_5d_avg > 0:
            result.volume_ratio_5d = float(latest['volume']) / vol_5d_avg
        
        # 判断价格变化
        prev_close = df.iloc[-2]['close']
        price_change = (latest['close'] - prev_close) / prev_close * 100
        
        # 量能状态判断
        if result.volume_ratio_5d >= self.VOLUME_HEAVY_RATIO:
            if price_change > 0:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                result.volume_trend = "放量上涨，多头力量强劲"
            else:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                result.volume_trend = "放量下跌，注意风险"
        elif result.volume_ratio_5d <= self.VOLUME_SHRINK_RATIO:
            if price_change > 0:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
                result.volume_trend = "缩量上涨，上攻动能不足"
            else:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
                result.volume_trend = "缩量回调，洗盘特征明显（好）"
        else:
            result.volume_status = VolumeStatus.NORMAL
            result.volume_trend = "量能正常"
    
    def _analyze_support_resistance(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析支撑压力位
        
        买点偏好：回踩 MA5/MA10 获得支撑
        """
        price = result.current_price
        
        # 检查是否在 MA5 附近获得支撑
        if result.ma5 > 0:
            ma5_distance = abs(price - result.ma5) / result.ma5
            if ma5_distance <= self.MA_SUPPORT_TOLERANCE and price >= result.ma5:
                result.support_ma5 = True
                result.support_levels.append(result.ma5)
        
        # 检查是否在 MA10 附近获得支撑
        if result.ma10 > 0:
            ma10_distance = abs(price - result.ma10) / result.ma10
            if ma10_distance <= self.MA_SUPPORT_TOLERANCE and price >= result.ma10:
                result.support_ma10 = True
                if result.ma10 not in result.support_levels:
                    result.support_levels.append(result.ma10)
        
        # MA20 作为重要支撑
        if result.ma20 > 0 and price >= result.ma20:
            result.support_levels.append(result.ma20)
        
        # 近期高点作为压力
        if len(df) >= 20:
            recent_high = df['high'].iloc[-20:].max()
            if recent_high > price:
                result.resistance_levels.append(recent_high)

    def _analyze_macd(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析 MACD 指标

        核心信号：
        - 零轴上金叉：最强买入信号
        - 金叉：DIF 上穿 DEA
        - 死叉：DIF 下穿 DEA
        """
        if len(df) < self.MACD_SLOW:
            result.macd_signal = "数据不足"
            return

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 获取 MACD 数据
        result.macd_dif = float(latest['MACD_DIF'])
        result.macd_dea = float(latest['MACD_DEA'])
        result.macd_bar = float(latest['MACD_BAR'])

        # 判断金叉死叉
        prev_dif_dea = prev['MACD_DIF'] - prev['MACD_DEA']
        curr_dif_dea = result.macd_dif - result.macd_dea

        # 金叉：DIF 上穿 DEA
        is_golden_cross = prev_dif_dea <= 0 and curr_dif_dea > 0

        # 死叉：DIF 下穿 DEA
        is_death_cross = prev_dif_dea >= 0 and curr_dif_dea < 0

        # 零轴穿越
        prev_zero = prev['MACD_DIF']
        curr_zero = result.macd_dif
        is_crossing_up = prev_zero <= 0 and curr_zero > 0
        is_crossing_down = prev_zero >= 0 and curr_zero < 0

        # 判断 MACD 状态
        if is_golden_cross and curr_zero > 0:
            result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
            result.macd_signal = "⭐ 零轴上金叉，强烈买入信号！"
        elif is_crossing_up:
            result.macd_status = MACDStatus.CROSSING_UP
            result.macd_signal = "⚡ DIF上穿零轴，趋势转强"
        elif is_golden_cross:
            result.macd_status = MACDStatus.GOLDEN_CROSS
            result.macd_signal = "✅ 金叉，趋势向上"
        elif is_death_cross:
            result.macd_status = MACDStatus.DEATH_CROSS
            result.macd_signal = "❌ 死叉，趋势向下"
        elif is_crossing_down:
            result.macd_status = MACDStatus.CROSSING_DOWN
            result.macd_signal = "⚠️ DIF下穿零轴，趋势转弱"
        elif result.macd_dif > 0 and result.macd_dea > 0:
            result.macd_status = MACDStatus.BULLISH
            result.macd_signal = "✓ 多头排列，持续上涨"
        elif result.macd_dif < 0 and result.macd_dea < 0:
            result.macd_status = MACDStatus.BEARISH
            result.macd_signal = "⚠ 空头排列，持续下跌"
        else:
            result.macd_status = MACDStatus.BULLISH
            result.macd_signal = " MACD 中性区域"

    def _analyze_rsi(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析 RSI 指标

        核心判断：
        - RSI > 70：超买，谨慎追高
        - RSI < 30：超卖，关注反弹
        - 40-60：中性区域
        """
        if len(df) < self.RSI_LONG:
            result.rsi_signal = "数据不足"
            return

        latest = df.iloc[-1]

        # 获取 RSI 数据
        result.rsi_6 = float(latest[f'RSI_{self.RSI_SHORT}'])
        result.rsi_12 = float(latest[f'RSI_{self.RSI_MID}'])
        result.rsi_24 = float(latest[f'RSI_{self.RSI_LONG}'])

        # 以中期 RSI(12) 为主进行判断
        rsi_mid = result.rsi_12

        # 判断 RSI 状态
        if rsi_mid > self.RSI_OVERBOUGHT:
            result.rsi_status = RSIStatus.OVERBOUGHT
            result.rsi_signal = f"⚠️ RSI超买({rsi_mid:.1f}>70)，短期回调风险高"
        elif rsi_mid > 60:
            result.rsi_status = RSIStatus.STRONG_BUY
            result.rsi_signal = f"✅ RSI强势({rsi_mid:.1f})，多头力量充足"
        elif rsi_mid >= 40:
            result.rsi_status = RSIStatus.NEUTRAL
            result.rsi_signal = f" RSI中性({rsi_mid:.1f})，震荡整理中"
        elif rsi_mid >= self.RSI_OVERSOLD:
            result.rsi_status = RSIStatus.WEAK
            result.rsi_signal = f"⚡ RSI弱势({rsi_mid:.1f})，关注反弹"
        else:
            result.rsi_status = RSIStatus.OVERSOLD
            result.rsi_signal = f"⭐ RSI超卖({rsi_mid:.1f}<30)，反弹机会大"

    def _generate_signal(self, result: TrendAnalysisResult) -> None:
        """
        生成买入信号 — 11 因子评分体系

        综合评分系统：
        - 趋势（25分）：多头排列得分高
        - 乖离率（14分）：接近 MA5 得分高
        - 量能三维（10分）：量比绝对值 + 方向 + 日内K线结构
        - 支撑（8分）：获得均线支撑得分高
        - MACD（12分）：金叉和多头得分高
        - RSI（8分）：超卖和强势得分高
        - 筹码（5分）：获利比例 + 集中度
        - 资金流（5分）：主力资金流向
        - 多周期动量（5分）：5/20/60日涨幅一致性
        - 日内K线（4分）：实体/影线结构
        - 估值（4分）：PE/PB 健康度
        """
        score = 0
        reasons = []
        risks = []

        # ============================================================
        # 1. 趋势评分（25分）
        # ============================================================
        trend_scores = {
            TrendStatus.STRONG_BULL: 25,
            TrendStatus.BULL: 21,
            TrendStatus.WEAK_BULL: 14,
            TrendStatus.CONSOLIDATION: 8,
            TrendStatus.WEAK_BEAR: 5,
            TrendStatus.BEAR: 2,
            TrendStatus.STRONG_BEAR: 0,
        }
        trend_score = trend_scores.get(result.trend_status, 8)
        score += trend_score

        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            reasons.append(f"✅ {result.trend_status.value}，顺势做多")
        elif result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            risks.append(f"⚠️ {result.trend_status.value}，不宜做多")

        # ============================================================
        # 2. 乖离率评分（14分，强势趋势补偿）
        # ============================================================
        bias = result.bias_ma5
        if bias != bias or bias is None:
            bias = 0.0
        base_threshold = get_config().bias_threshold
        trend_strength = result.trend_strength if result.trend_strength == result.trend_strength else 0.0
        if result.trend_status == TrendStatus.STRONG_BULL and (trend_strength or 0) >= 70:
            effective_threshold = base_threshold * 1.5
            is_strong_trend = True
        else:
            effective_threshold = base_threshold
            is_strong_trend = False

        if bias < 0:
            if bias > -3:
                score += 14; reasons.append(f"✅ 价格略低于MA5({bias:.1f}%)，回踩买点")
            elif bias > -5:
                score += 11; reasons.append(f"✅ 价格回踩MA5({bias:.1f}%)，观察支撑")
            else:
                score += 5; risks.append(f"⚠️ 乖离率过大({bias:.1f}%)，可能破位")
        elif bias < 2:
            score += 12; reasons.append(f"✅ 价格贴近MA5({bias:.1f}%)，介入好时机")
        elif bias < base_threshold:
            score += 9; reasons.append(f"⚡ 价格略高于MA5({bias:.1f}%)，可小仓介入")
        elif bias > effective_threshold:
            score += 2; risks.append(f"❌ 乖离率过高({bias:.1f}%)，严禁追高！")
        elif bias > base_threshold and is_strong_trend:
            score += 6; reasons.append(f"⚡ 强势趋势中乖离率偏高({bias:.1f}%)，可轻仓追踪")
        else:
            score += 2; risks.append(f"❌ 乖离率过高({bias:.1f}%)，严禁追高！")

        # ============================================================
        # 3. 量能三维评分（10分）：绝对值 + 方向 + 日内结构
        # ============================================================
        # 维度1: 量比绝对值 (0-4分)
        vr = result.volume_ratio_5d
        vol_abs_score = 0
        if vr >= 1.5:    vol_abs_score = 4; reasons.append("✅ 量比≥1.5，放量活跃")
        elif vr >= 1.0:  vol_abs_score = 3; reasons.append("✅ 量比≥1.0，量能正常")
        elif vr >= 0.7:  vol_abs_score = 1  # 偏低但不处罚
        else:            vol_abs_score = 0; risks.append("⚠️ 量比<0.7，地量交投清淡")

        # 维度2: 量价方向 (0-4分)
        vol_dir_score = 0
        if result.volume_status == VolumeStatus.HEAVY_VOLUME_UP:
            vol_dir_score = 4; reasons.append("✅ 放量上涨，量价齐升")
        elif result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            vol_dir_score = 3; reasons.append("✅ 缩量回调，整理蓄力")
        elif result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            vol_dir_score = 0; risks.append("⚠️ 放量下跌")
        elif result.volume_status == VolumeStatus.SHRINK_VOLUME_UP:
            vol_dir_score = 1; risks.append("⚠️ 无量上涨")
        else:
            vol_dir_score = 2

        # 维度3: 日内K线量能确认 (0-2分)
        kline_vol = 0
        if result.is_bullish_candle and result.body_pct > 0.5:
            kline_vol = 2; reasons.append("✅ 阳线实体有力")
        elif result.is_bullish_candle:
            kline_vol = 1
        elif result.body_pct > 2 and not result.is_bullish_candle:
            kline_vol = 0; risks.append("⚠️ 中阴线空方主导")

        score += vol_abs_score + vol_dir_score + kline_vol

        # ============================================================
        # 4. 支撑评分（8分）
        # ============================================================
        if result.support_ma5:
            score += 4; reasons.append("✅ MA5支撑有效")
        if result.support_ma10:
            score += 4; reasons.append("✅ MA10支撑有效")

        # ============================================================
        # 5. MACD 评分（12分）
        # ============================================================
        macd_scores = {
            MACDStatus.GOLDEN_CROSS_ZERO: 12,
            MACDStatus.GOLDEN_CROSS: 10,
            MACDStatus.CROSSING_UP: 8,
            MACDStatus.BULLISH: 6,
            MACDStatus.BEARISH: 1,
            MACDStatus.CROSSING_DOWN: 0,
            MACDStatus.DEATH_CROSS: 0,
        }
        macd_score = macd_scores.get(result.macd_status, 4)
        score += macd_score

        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS]:
            reasons.append(f"✅ {result.macd_signal}")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN]:
            risks.append(f"⚠️ {result.macd_signal}")
        else:
            reasons.append(result.macd_signal)

        # MACD 钝化检测：DIF 在零轴上但柱状图收窄 (>20%收缩 = 动能在衰减)
        if (result.macd_status == MACDStatus.BULLISH
                and result.macd_bar > 0
                and result.macd_bar < result.macd_dif * 0.15):
            risks.append("⚠️ MACD柱收窄，上行动能减弱")

        # ============================================================
        # 6. RSI 评分（8分）
        # ============================================================
        rsi_scores = {
            RSIStatus.OVERSOLD: 8,
            RSIStatus.STRONG_BUY: 6,
            RSIStatus.NEUTRAL: 4,
            RSIStatus.WEAK: 2,
            RSIStatus.OVERBOUGHT: 0,
        }
        rsi_score = rsi_scores.get(result.rsi_status, 4)
        score += rsi_score

        if result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.STRONG_BUY]:
            reasons.append(f"✅ {result.rsi_signal}")
        elif result.rsi_status == RSIStatus.OVERBOUGHT:
            risks.append(f"⚠️ {result.rsi_signal}")
        else:
            reasons.append(result.rsi_signal)

        # ============================================================
        # 7. 筹码评分（5分）
        # ============================================================
        chip_score = 0
        if result.chip_profit_ratio >= 50:
            chip_score += 3; reasons.append(f"✅ 获利盘{result.chip_profit_ratio:.0f}%，筹码健康")
        elif result.chip_profit_ratio > 0:
            chip_score += 1
        if result.chip_concentration > 0 and result.chip_concentration < 12:
            chip_score += 2; reasons.append(f"✅ 筹码集中度{result.chip_concentration:.1f}%，集中良好")
        elif result.chip_concentration > 0:
            chip_score += 1
        score += chip_score

        # ============================================================
        # 8. 资金流评分（5分）
        # ============================================================
        flow_score = 0
        inflow = result.main_net_inflow_5d
        if inflow > 0:
            flow_score = min(5, int(inflow / 20000000))  # 每2000万+1分, 上限5
            if flow_score >= 2:
                reasons.append(f"✅ 主力5日净流入{inflow/1e4:.0f}万")
        elif inflow < 0:
            outflow_pct = abs(inflow) / 1e8  # 相对亿元
            if outflow_pct < 0.5:    # 流出<5000万
                flow_score = 3; reasons.append(f"⚡ 主力微幅流出{abs(inflow)/1e4:.0f}万，噪声级别")
            elif outflow_pct < 2:    # 流出5000万-2亿
                flow_score = 1; risks.append(f"⚠️ 主力5日净流出{abs(inflow)/1e4:.0f}万")
            else:
                flow_score = 0; risks.append(f"⚠️ 主力持续流出{abs(inflow)/1e4:.0f}万")
        score += flow_score

        # ============================================================
        # 9. 多周期动量评分（5分）
        # ============================================================
        momentum_score = 0
        changes = [
            (result.change_5d, "5日"),
            (result.change_20d, "20日"),
            (result.change_60d, "60日"),
        ]
        # Only count periods that actually have data (>0 means computed)
        valid_changes = [(ch, lbl) for ch, lbl in changes if ch != 0.0]
        total_periods = len(valid_changes) if valid_changes else 1
        aligned_count = sum(1 for ch, _ in valid_changes if ch > 0)
        
        if aligned_count == total_periods and total_periods >= 2:
            momentum_score = 5; reasons.append("✅ 多周期动量全正，中期趋势确认")
        elif aligned_count >= 2:
            momentum_score = 3
        elif aligned_count >= 1 and total_periods >= 2:
            momentum_score = 1
        elif aligned_count == 1 and total_periods == 1:
            momentum_score = 2  # single period positive, no negative data
        else:
            momentum_score = 0; risks.append("⚠️ 多周期动量全负")
        score += momentum_score

        # ============================================================
        # 10. 日内K线结构评分（4分）
        # ============================================================
        kline_score = 0
        if result.is_bullish_candle:
            kline_score += 2; reasons.append("✅ 当日阳线")
            if result.lower_shadow_pct > result.body_pct * 1.5:
                kline_score += 2; reasons.append("✅ 长下影线，抄底支撑确认")
            elif result.lower_shadow_pct > result.body_pct:
                kline_score += 1
        else:
            if result.lower_shadow_pct > result.body_pct * 2:
                kline_score += 2; reasons.append("✅ 阴线长下影，承接有力")
            elif result.lower_shadow_pct > result.body_pct:
                kline_score += 1
            if result.body_pct > 2 and result.upper_shadow_pct < result.body_pct * 0.3:
                kline_score += 0; risks.append("⚠️ 中阴线且上影线短，空方主导")
        score += kline_score

        # ============================================================
        # 11. 估值评分（4分）
        # ============================================================
        val_score = 0
        if result.pe_ratio > 0:
            if result.pe_ratio < 20:
                val_score += 2; reasons.append(f"✅ PE={result.pe_ratio:.1f}，估值偏低")
            elif result.pe_ratio < 40:
                val_score += 1
            elif result.pe_ratio > 100:
                risks.append(f"⚠️ PE={result.pe_ratio:.0f}，估值偏高")
        if result.pb_ratio > 0:
            if result.pb_ratio < 3:
                val_score += 2; reasons.append(f"✅ PB={result.pb_ratio:.2f}，资产合理")
            elif result.pb_ratio < 5:
                val_score += 1
            elif result.pb_ratio > 10:
                risks.append(f"⚠️ PB={result.pb_ratio:.1f}，估值偏高")
        score += val_score

        # ============================================================
        # 综合判断
        # ============================================================
        result.signal_score = score
        result.signal_reasons = reasons
        result.risk_factors = risks

        # Per-factor score diagnostics for verification
        logger.info(
            "[Scoring] %s total=%d | ma5=%.2f ma10=%.2f ma20=%.2f bias=%.2f "
            "vol_ratio=%.2f vol_status=%s macd=%s rsi_12=%.1f "
            "chip=%.1f%% conc=%.1f%% flow=%.0f PE=%.1f PB=%.2f "
            "chg5=%.1f chg20=%.1f chg60=%.1f candle=%s body=%.2f%% "
            "| factors=%s",
            result.code, score,
            result.ma5, result.ma10, result.ma20, result.bias_ma5,
            result.volume_ratio_5d, result.volume_status.value if result.volume_status else '?',
            result.macd_status.value if result.macd_status else '?',
            result.rsi_12,
            result.chip_profit_ratio, result.chip_concentration,
            result.main_net_inflow_5d, result.pe_ratio, result.pb_ratio,
            result.change_5d, result.change_20d, result.change_60d,
            'bull' if result.is_bullish_candle else 'bear', result.body_pct,
            result.signal_reasons[:8],
        )

        if score >= 75 and result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            result.buy_signal = BuySignal.STRONG_BUY
        elif score >= 60 and result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]:
            result.buy_signal = BuySignal.BUY
        elif score >= 45:
            result.buy_signal = BuySignal.HOLD
        elif score >= 30:
            result.buy_signal = BuySignal.WAIT
        elif result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            result.buy_signal = BuySignal.STRONG_SELL
        else:
            result.buy_signal = BuySignal.SELL
    
    def format_analysis(self, result: TrendAnalysisResult) -> str:
        """
        格式化分析结果为文本

        Args:
            result: 分析结果

        Returns:
            格式化的分析文本
        """
        lines = [
            f"=== {result.code} 趋势分析 ===",
            f"",
            f"📊 趋势判断: {result.trend_status.value}",
            f"   均线排列: {result.ma_alignment}",
            f"   趋势强度: {result.trend_strength}/100",
            f"",
            f"📈 均线数据:",
            f"   现价: {result.current_price:.2f}",
            f"   MA5:  {result.ma5:.2f} (乖离 {result.bias_ma5:+.2f}%)",
            f"   MA10: {result.ma10:.2f} (乖离 {result.bias_ma10:+.2f}%)",
            f"   MA20: {result.ma20:.2f} (乖离 {result.bias_ma20:+.2f}%)",
            f"",
            f"📊 量能分析: {result.volume_status.value}",
            f"   量比(vs5日): {result.volume_ratio_5d:.2f}",
            f"   量能趋势: {result.volume_trend}",
            f"",
            f"📈 MACD指标: {result.macd_status.value}",
            f"   DIF: {result.macd_dif:.4f}",
            f"   DEA: {result.macd_dea:.4f}",
            f"   MACD: {result.macd_bar:.4f}",
            f"   信号: {result.macd_signal}",
            f"",
            f"📊 RSI指标: {result.rsi_status.value}",
            f"   RSI(6): {result.rsi_6:.1f}",
            f"   RSI(12): {result.rsi_12:.1f}",
            f"   RSI(24): {result.rsi_24:.1f}",
            f"   信号: {result.rsi_signal}",
            f"",
            f"🎯 操作建议: {result.buy_signal.value}",
            f"   综合评分: {result.signal_score}/100",
        ]

        if result.signal_reasons:
            lines.append(f"")
            lines.append(f"✅ 买入理由:")
            for reason in result.signal_reasons:
                lines.append(f"   {reason}")

        if result.risk_factors:
            lines.append(f"")
            lines.append(f"⚠️ 风险因素:")
            for risk in result.risk_factors:
                lines.append(f"   {risk}")

        return "\n".join(lines)


def analyze_stock(df: pd.DataFrame, code: str) -> TrendAnalysisResult:
    """
    便捷函数：分析单只股票
    
    Args:
        df: 包含 OHLCV 数据的 DataFrame
        code: 股票代码
        
    Returns:
        TrendAnalysisResult 分析结果
    """
    analyzer = StockTrendAnalyzer()
    return analyzer.analyze(df, code)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 模拟数据测试
    import numpy as np
    
    dates = pd.date_range(start='2025-01-01', periods=60, freq='D')
    np.random.seed(42)
    
    # 模拟多头排列的数据
    base_price = 10.0
    prices = [base_price]
    for i in range(59):
        change = np.random.randn() * 0.02 + 0.003  # 轻微上涨趋势
        prices.append(prices[-1] * (1 + change))
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p * (1 + np.random.uniform(0, 0.02)) for p in prices],
        'low': [p * (1 - np.random.uniform(0, 0.02)) for p in prices],
        'close': prices,
        'volume': [np.random.randint(1000000, 5000000) for _ in prices],
    })
    
    analyzer = StockTrendAnalyzer()
    result = analyzer.analyze(df, '000001')
    print(analyzer.format_analysis(result))
