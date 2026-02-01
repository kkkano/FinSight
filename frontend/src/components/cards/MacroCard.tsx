/**
 * Macro Card - 宏观数据占位
 *
 * 未来扩展：GDP、CPI、利率等宏观指标
 */

interface MacroCardProps {
  loading?: boolean;
}

export function MacroCard({ loading }: MacroCardProps) {
  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-32 animate-pulse">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="h-16 bg-fin-border rounded" />
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      <h3 className="text-sm font-semibold text-fin-text mb-3">宏观数据</h3>
      <div className="flex items-center justify-center h-24 text-fin-muted text-sm border-2 border-dashed border-fin-border rounded-lg">
        <div className="text-center">
          <div className="mb-1">🏗️ 建设中</div>
          <div className="text-xs">GDP、CPI、利率等宏观指标</div>
        </div>
      </div>
    </div>
  );
}

export default MacroCard;
