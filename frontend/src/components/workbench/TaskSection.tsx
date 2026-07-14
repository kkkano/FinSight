import { ListTodo, Loader2 } from 'lucide-react';

import type { WorkbenchTasksController } from '../../hooks/useWorkbenchTasks';
import { Card } from '../ui/Card';
import { HISTORY_STATUS_LABEL, formatTime } from './taskStateMachine';
import { TaskCard } from './TaskCard';

interface TaskSectionProps {
  controller: WorkbenchTasksController;
}

function TaskSection({ controller }: TaskSectionProps) {
  const {
    taskRunItems,
    history,
    loading,
    error,
    handleClick,
    handleResume,
    handleCancelInterrupt,
  } = controller;
  const recentHistory = history.slice(0, 5);

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-fin-text">
        <ListTodo size={16} className="text-fin-primary" />
        今日任务
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-2 text-xs text-fin-muted">
          <Loader2 size={12} className="animate-spin" />
          加载中...
        </div>
      )}
      {error && !loading && <div className="py-2 text-xs text-fin-danger">加载失败: {error}</div>}

      <div className="space-y-1.5">
        {!loading && taskRunItems.length === 0 && !error && (
          <div className="py-2 text-xs text-fin-muted">暂无建议任务</div>
        )}
        {taskRunItems.map(({ identity, task, run }) => (
          <TaskCard
            key={identity}
            task={task}
            run={run}
            onClick={handleClick}
            onResume={handleResume}
            onCancelInterrupt={handleCancelInterrupt}
          />
        ))}
      </div>

      {recentHistory.length > 0 && (
        <div className="mt-4 border-t border-fin-border pt-3">
          <div className="mb-2 text-2xs font-medium text-fin-text-secondary">执行历史</div>
          <div className="space-y-1">
            {recentHistory.map((item, index) => (
              <div key={`${item.taskId}-${item.at}-${index}`} className="flex items-center gap-2 text-2xs text-fin-muted">
                <span className="w-10 shrink-0">{formatTime(item.at)}</span>
                <span className={`w-14 shrink-0 ${
                  item.status === 'done'
                    ? 'text-emerald-500'
                    : item.status === 'error'
                      ? 'text-red-500'
                      : item.status === 'expired'
                        ? 'text-slate-400'
                        : 'text-amber-500'
                }`}>
                  {HISTORY_STATUS_LABEL[item.status] ?? item.status}
                </span>
                <span className="min-w-0 flex-1 truncate">{item.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export { TaskSection };
export type { TaskSectionProps };
