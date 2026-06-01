import type React from 'react';
import type { AgentOpinion, ReportDetails as ReportDetailsType, ReportLanguage } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportAgentChainProps {
  details?: ReportDetailsType;
  language?: ReportLanguage;
}

const SIGNAL_CN_MAP: Record<string, string> = {
  buy: '买入',
  strong_buy: '强烈买入',
  hold: '持有',
  sell: '卖出',
  strong_sell: '强烈卖出',
  watch: '观望',
};

const SIGNAL_EN_MAP: Record<string, string> = {
  buy: 'BUY',
  strong_buy: 'STRONG BUY',
  hold: 'HOLD',
  sell: 'SELL',
  strong_sell: 'STRONG SELL',
  watch: 'WATCH',
};

const SIGNAL_TONE: Record<string, { bg: string; text: string; border: string }> = {
  buy: { bg: 'bg-success/10', text: 'text-success', border: 'border-success/30' },
  strong_buy: { bg: 'bg-success/20', text: 'text-success', border: 'border-success/50' },
  hold: { bg: 'bg-warning/10', text: 'text-warning', border: 'border-warning/30' },
  sell: { bg: 'bg-danger/10', text: 'text-danger', border: 'border-danger/30' },
  strong_sell: { bg: 'bg-danger/20', text: 'text-danger', border: 'border-danger/50' },
  watch: { bg: 'bg-secondary/10', text: 'text-secondary-text', border: 'border-secondary/30' },
};

const CONFIDENCE_TONE = (score: number): string => {
  if (score >= 0.75) return 'text-success';
  if (score >= 0.5) return 'text-warning';
  return 'text-danger';
};

const getSignalLabel = (signal: string, lang: string): string => {
  const map = lang === 'en' ? SIGNAL_EN_MAP : SIGNAL_CN_MAP;
  return map[signal] || signal;
};

const getSignalStyle = (signal: string) => {
  return SIGNAL_TONE[signal] || SIGNAL_TONE.watch;
};

/**
 * Agent 分析链路组件
 *
 * 从 contextSnapshot 中提取 agent_opinions 数组，
 * 结构化展示每个 Agent 的信号、置信度、分析逻辑和关键价位。
 */
export const ReportAgentChain: React.FC<ReportAgentChainProps> = ({
  details,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);

  // Extract agent_opinions from contextSnapshot
  const contextSnapshot = details?.contextSnapshot;
  let opinions: AgentOpinion[] = [];
  if (contextSnapshot && typeof contextSnapshot === 'object') {
    const raw = (contextSnapshot as Record<string, unknown>).agent_opinions;
    if (Array.isArray(raw)) {
      opinions = raw as AgentOpinion[];
    }
  }

  if (opinions.length === 0) {
    return null;
  }

  const formatConfidence = (val: number): string =>
    Number.isFinite(val) ? `${(val * 100).toFixed(0)}%` : '--';

  const formatLevel = (val: number | undefined): string =>
    val != null && Number.isFinite(val) ? val.toFixed(2) : '--';

  // Key level display names
  const levelLabels: Record<string, string> = reportLanguage === 'en'
    ? { support: 'Support', resistance: 'Resistance', stop_loss: 'Stop Loss', take_profit: 'Take Profit' }
    : { support: '支撑', resistance: '压力', stop_loss: '止损', take_profit: '止盈' };

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        eyebrow={reportLanguage === 'en' ? 'DECISION PIPELINE' : '决策链路'}
        title={text.agentChain}
        className="mb-4"
      />

      <div className="space-y-4">
        {opinions.map((op, idx) => {
          const signalStyle = getSignalStyle(op.signal);
          const isLast = idx === opinions.length - 1;
          const keyLevels = op.key_levels || {};
          const hasLevels = Object.keys(keyLevels).length > 0;

          return (
            <div key={`${op.agent_name}-${idx}`} className="relative">
              {/* Agent card */}
              <div className="home-subpanel rounded-lg p-4 border border-border/50">
                {/* Header: agent name + signal badge */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="home-accent-chip px-2 py-0.5 text-xs font-mono uppercase">
                      {op.agent_name}
                    </span>
                    <span className="text-xs text-muted-text">
                      #{idx + 1}/{opinions.length}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    {/* Confidence */}
                    <div className="flex items-center gap-1.5">
                      <span className="text-2xs text-muted-text uppercase tracking-wider">
                        {text.confidence}
                      </span>
                      <span className={`text-sm font-mono font-semibold ${CONFIDENCE_TONE(op.confidence)}`}>
                        {formatConfidence(op.confidence)}
                      </span>
                    </div>
                    {/* Signal badge */}
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border ${signalStyle.bg} ${signalStyle.text} ${signalStyle.border}`}
                    >
                      {getSignalLabel(op.signal, reportLanguage)}
                    </span>
                  </div>
                </div>

                {/* Reasoning */}
                {op.reasoning && (
                  <div className="mb-3">
                    <span className="label-uppercase">{text.reasoningLabel}</span>
                    <p className="mt-1.5 text-sm leading-6 text-foreground whitespace-pre-wrap max-w-full break-words">
                      {op.reasoning}
                    </p>
                  </div>
                )}

                {/* Key Levels */}
                {hasLevels && (
                  <div>
                    <span className="label-uppercase">{text.keyLevels}</span>
                    <div className="mt-1.5 grid grid-cols-2 gap-2">
                      {Object.entries(levelLabels).map(([key, label]) => {
                        const val = keyLevels[key];
                        if (val == null || !Number.isFinite(val)) return null;
                        return (
                          <div
                            key={key}
                            className="flex items-center justify-between rounded-md bg-base px-2.5 py-1.5"
                          >
                            <span className="text-xs text-muted-text">{label}</span>
                            <span className="text-sm font-mono font-medium text-foreground">
                              {formatLevel(val)}
                            </span>
                          </div>
                        );
                      })}
                      {/* Render any extra levels not in standard labels */}
                      {Object.entries(keyLevels)
                        .filter(([k]) => !(k in levelLabels))
                        .map(([key, val]) => (
                          <div
                            key={key}
                            className="flex items-center justify-between rounded-md bg-base px-2.5 py-1.5"
                          >
                            <span className="text-xs text-muted-text capitalize">{key.replace(/_/g, ' ')}</span>
                            <span className="text-sm font-mono font-medium text-foreground">
                              {formatLevel(val)}
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Connector arrow between agents */}
              {!isLast && (
                <div className="flex justify-center py-1">
                  <svg className="w-4 h-4 text-muted-text/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
};
