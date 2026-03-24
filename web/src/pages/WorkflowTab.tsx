import { useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useWorkflowStore } from "../stores/useWorkflowStore";
import { classNames } from "../utils/classNames";

type WorkflowTabProps = {
  groupId: string;
  isDark: boolean;
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (minutes < 60) return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString();
}

function statusColor(status: string): string {
  switch (status) {
    case "completed":
      return "text-emerald-500";
    case "failed":
      return "text-rose-500";
    case "running":
      return "text-sky-500";
    case "pending":
      return "text-amber-500";
    default:
      return "text-slate-500";
  }
}

function decisionColor(decision: string): string {
  switch (decision) {
    case "approved":
      return "bg-emerald-500/10 text-emerald-600 border-emerald-500/30";
    case "modified":
      return "bg-amber-500/10 text-amber-600 border-amber-500/30";
    case "rejected":
      return "bg-rose-500/10 text-rose-600 border-rose-500/30";
    case "deferred":
      return "bg-slate-500/10 text-slate-600 border-slate-500/30";
    default:
      return "bg-slate-500/10 text-slate-500 border-slate-500/30";
  }
}

function taskTypeIcon(type: string): string {
  switch (type) {
    case "frontend":
      return "F";
    case "backend":
      return "B";
    default:
      return "G";
  }
}

function taskTypeBg(type: string): string {
  switch (type) {
    case "frontend":
      return "bg-purple-500/20 text-purple-600";
    case "backend":
      return "bg-blue-500/20 text-blue-600";
    default:
      return "bg-slate-500/20 text-slate-600";
  }
}

export function WorkflowTab({ groupId, isDark }: WorkflowTabProps) {
  const { t } = useTranslation("layout");
  const {
    pendingSuggestions,
    decisions,
    progress,
    isLoading,
    error,
    refreshPending,
    refreshProgress,
    processBatch,
    clearWorkflow,
  } = useWorkflowStore();

  const [activeTab, setActiveTab] = useState<"progress" | "pending" | "decisions">("progress");

  // Refresh on mount and periodically
  useEffect(() => {
    refreshPending();
    refreshProgress(groupId);

    const interval = setInterval(() => {
      if (progress?.status === "running") {
        refreshProgress(groupId, progress.workflow_id);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [groupId, refreshPending, refreshProgress, progress?.status, progress?.workflow_id]);

  // Calculate stats
  const stats = useMemo(() => {
    const tasks = progress?.tasks || { total: 0, completed: 0, failed: 0, running: 0, pending: 0 };
    const progressPct = tasks.total > 0 ? Math.round((tasks.completed / tasks.total) * 100) : 0;
    return { ...tasks, progressPct };
  }, [progress]);

  const handleProcess = async (suggestionId: string) => {
    await processBatch(groupId, suggestionId);
  };

  const handleClear = async (workflowId: string) => {
    if (confirm("Clear workflow state? This cannot be undone.")) {
      await clearWorkflow(workflowId);
    }
  };

  return (
    <div className="flex-1 min-h-0 overflow-auto p-5">
      <div className="mx-auto max-w-5xl">
        {/* Header */}
        <div className="mb-6">
          <div className="text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
            Ralph-Foreman
          </div>
          <div className="mt-2 text-xl font-semibold text-[var(--color-text-primary)]">
            Workflow Dashboard
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide">Status</div>
            <div className={classNames(
              "mt-1 text-lg font-semibold",
              progress?.status === "running" ? "text-emerald-500" : "text-slate-500"
            )}>
              {progress?.status === "running" ? "Running" : "Idle"}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide">Progress</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {stats.completed}/{stats.total} ({stats.progressPct}%)
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide">Batches</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {progress?.batches?.completed || 0}/{progress?.batches?.total || 0}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-xs text-[var(--color-text-muted)] uppercase tracking-wide">Duration</div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {formatDuration(progress?.duration?.workflow_seconds || 0)}
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        {progress?.status === "running" && (
          <div className="glass-card rounded-xl p-4 mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-[var(--color-text-primary)]">
                Workflow: {progress.workflow_id?.slice(0, 16)}...
              </span>
              <span className="text-xs text-[var(--color-text-muted)]">
                Batch: {progress.current_batch?.slice(0, 8)}
              </span>
            </div>
            <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-500"
                style={{ width: `${stats.progressPct}%` }}
              />
            </div>
            <div className="mt-2 flex gap-4 text-xs text-[var(--color-text-muted)]">
              <span className="text-emerald-500">{stats.completed} completed</span>
              <span className="text-sky-500">{stats.running} running</span>
              <span className="text-amber-500">{stats.pending} pending</span>
              {stats.failed > 0 && <span className="text-rose-500">{stats.failed} failed</span>}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2 mb-4">
          {(["progress", "pending", "decisions"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={classNames(
                "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                activeTab === tab
                  ? "bg-cyan-500/20 text-cyan-600 border border-cyan-500/30"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-tertiary)]"
              )}
            >
              {tab === "progress" && "Recent Events"}
              {tab === "pending" && `Pending (${pendingSuggestions.length})`}
              {tab === "decisions" && `Decisions (${decisions.length})`}
            </button>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-600 text-sm">
            {error}
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full" />
          </div>
        )}

        {/* Content */}
        {!isLoading && activeTab === "progress" && (
          <div className="glass-card rounded-xl p-4">
            <div className="text-sm font-medium text-[var(--color-text-primary)] mb-3">Recent Events</div>
            {(!progress?.recent_events || progress.recent_events.length === 0) ? (
              <div className="text-sm text-[var(--color-text-muted)] py-4 text-center">
                No recent events
              </div>
            ) : (
              <div className="space-y-2">
                {progress.recent_events.slice().reverse().map((event, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-3 p-2 rounded-lg bg-[var(--color-bg-secondary)]"
                  >
                    <span className="text-xs text-[var(--color-text-muted)]">
                      {formatTime(event.timestamp)}
                    </span>
                    <span className={classNames(
                      "text-xs font-medium px-2 py-0.5 rounded",
                      event.type === "batch_started" ? "bg-sky-500/20 text-sky-600" :
                      event.type === "task_completed" ? "bg-emerald-500/20 text-emerald-600" :
                      event.type === "task_failed" ? "bg-rose-500/20 text-rose-600" :
                      event.type === "batch_completed" ? "bg-purple-500/20 text-purple-600" :
                      "bg-slate-500/20 text-slate-600"
                    )}>
                      {event.type}
                    </span>
                    {String(event.task_id ?? "") && (
                      <span className="text-xs text-[var(--color-text-secondary)]">
                        Task: {String(event.task_id)}
                      </span>
                    )}
                    {String(event.batch_id ?? "") && (
                      <span className="text-xs text-[var(--color-text-muted)]">
                        Batch: {String(event.batch_id).slice(0, 8)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isLoading && activeTab === "pending" && (
          <div className="space-y-4">
            {pendingSuggestions.length === 0 ? (
              <div className="glass-card rounded-xl p-8 text-center text-[var(--color-text-muted)]">
                No pending batch suggestions
              </div>
            ) : (
              pendingSuggestions.map((suggestion) => (
                <div key={suggestion.suggestion_id} className="glass-card rounded-xl p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="text-sm font-medium text-[var(--color-text-primary)]">
                        {suggestion.workflow_id}
                      </div>
                      <div className="text-xs text-[var(--color-text-muted)]">
                        {suggestion.suggestion_id.slice(0, 8)} | {suggestion.tasks.length} tasks
                      </div>
                    </div>
                    <button
                      onClick={() => handleProcess(suggestion.suggestion_id)}
                      className="px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium rounded-lg transition-colors"
                    >
                      Process
                    </button>
                  </div>
                  {suggestion.rationale && (
                    <div className="text-xs text-[var(--color-text-secondary)] mb-3">
                      {suggestion.rationale}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {suggestion.tasks.map((task) => (
                      <div
                        key={task.id}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-bg-secondary)]"
                      >
                        <span className={classNames(
                          "w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold",
                          taskTypeBg(task.type)
                        )}>
                          {taskTypeIcon(task.type)}
                        </span>
                        <span className="text-sm text-[var(--color-text-primary)]">{task.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {!isLoading && activeTab === "decisions" && (
          <div className="space-y-4">
            {decisions.length === 0 ? (
              <div className="glass-card rounded-xl p-8 text-center text-[var(--color-text-muted)]">
                No decisions yet
              </div>
            ) : (
              decisions.map((decision) => (
                <div key={decision.decision_id} className="glass-card rounded-xl p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--color-text-primary)]">
                          {decision.workflow_id}
                        </span>
                        <span className={classNames(
                          "px-2 py-0.5 text-xs font-medium rounded border",
                          decisionColor(decision.decision)
                        )}>
                          {decision.decision}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--color-text-muted)] mt-1">
                        {decision.decision_id.slice(0, 12)} | {new Date(decision.created_at).toLocaleString()}
                      </div>
                    </div>
                    <button
                      onClick={() => handleClear(decision.workflow_id)}
                      className="px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-rose-500 transition-colors"
                    >
                      Clear
                    </button>
                  </div>
                  <div className="text-xs text-[var(--color-text-secondary)] mb-3">
                    {decision.reason}
                  </div>
                  <div className="flex gap-4 text-xs">
                    <span className="text-emerald-500">
                      Approved: {decision.approved_tasks.length}
                    </span>
                    {decision.rejected_tasks.length > 0 && (
                      <span className="text-rose-500">
                        Rejected: {decision.rejected_tasks.length}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
