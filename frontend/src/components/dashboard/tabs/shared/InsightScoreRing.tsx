/**
 * InsightScoreRing - Compact score ring for AI insight cards.
 *
 * Displays a small SVG ring with numeric score (0-10) and color coding.
 * Designed to be embedded inside AiInsightCard, smaller than the overview ScoreRing.
 */
import { useMemo } from 'react';

interface InsightScoreRingProps {
  score: number;
  size?: number;
}

const STROKE_WIDTH = 3;

export function InsightScoreRing({ score, size = 44 }: InsightScoreRingProps) {
  const radius = (size - STROKE_WIDTH * 2) / 2;
  const circumference = 2 * Math.PI * radius;

  const { progress, color } = useMemo(() => {
    const clamped = Math.max(0, Math.min(10, score));
    const p = clamped / 10;
    const c =
      clamped >= 7
        ? 'text-fin-success'
        : clamped >= 4
          ? 'text-fin-warning'
          : 'text-fin-danger';
    return { progress: p, color: c };
  }, [score]);

  const strokeDashoffset = circumference * (1 - progress);

  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg
        className="w-full h-full -rotate-90"
        viewBox={`0 0 ${size} ${size}`}
      >
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={STROKE_WIDTH}
          className="stroke-fin-border"
        />
        {/* Progress ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={STROKE_WIDTH}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          className={`${color} stroke-current transition-all duration-500`}
        />
      </svg>
      {/* Score text */}
      <div className="absolute inset-0 flex items-center justify-center">
        <span className={`text-sm font-bold ${color}`}>
          {score.toFixed(1)}
        </span>
      </div>
    </div>
  );
}

export default InsightScoreRing;
