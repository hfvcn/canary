import { useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useWorkflowStore } from "../stores/useWorkflowStore";
import type { WorkflowAgentAssignment } from "../stores/useWorkflowStore";
import { classNames } from "../utils/classNames";
import { RUNTIME_INFO, getRuntimeColor } from "../types";

type WorkflowTabProps = {
  groupId: string;
  isDark: boolean;
  onNavigateToActor?: (actorId: string) => void;
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

function statusBg(status: string): string {
  switch (status) {
    case "completed":
      return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30";
    case "failed":
      return "bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30";
    case "running":
      return "bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30";
    case "pending":
      return "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30";
    default:
      return "bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/30";
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
      return "bg-purple-500/20 text-purple-600 dark:text-purple-400";
    case "backend":
      return "bg-blue-500/20 text-blue-600 dark:text-blue-400";
    default:
      return "bg-slate-500/20 text-slate-600 dark:text-slate-400";
  }
}

function runtimeLabel(runtime: string): string {
  return RUNTIME_INFO[runtime]?.label || runtime || "Unknown";
}

// ─── Agent Assignment Card ────────────────────────────────────────────────────

function AssignmentCard({
  assignment,
  isDark,
  onNavigateToActor,
}: {
  assignment: WorkflowAgentAssignment;
  isDark: boolean;
  onNavigateToActor?: (actorId: string) => void;
}) {
  const rc = getRuntimeColor(assignment.model_runtime, isDark);
  const status = assignment.status || "pending";

  return (
    <div className="glass-card rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* Task title + type */}
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={classNames(
                "w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold flex-shrink-0",
                taskTypeBg(assignment.task_type)
              )}
            >
              {taskTypeIcon(assignment.task_type)}
            </span>
            <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">
              {assignment.task_title}
            </span>
          </div>

          {/* Agent + model */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              onClick={() => onNavigateToActor?.(assignment.agent_id)}
              className={classNames(
                "text-xs px-2 py-1 rounded-lg border transition-colors cursor-pointer",
                rc.bg, rc.text, rc.border
              )}
              title={`Go to ${assignment.agent_name}`}
            >
              {assignment.agent_name || assignment.agent_id}
              {assignment.is_new_agent && (
                <span className="ml-1 opacity-60">new</span>
              )}
            </button>
            <span className="text-[11px] text-[var(--color-text-muted)]">
              {runtimeLabel(assignment.model_runtime)}
              {assignment.model_id && (
                <span className="ml-1 opacity-70">({assignment.model_id})</span>
              )}
            </span>
          </div>

          {/* Duration + changed files */}
          {(assignment.duration_seconds || assignment.changed_files?.length) && (
            <div className="mt-1.5 flex items-center gap-3 text-[11px] text-[var(--color-text-muted)]">
              {assignment.duration_seconds != null && assignment.duration_seconds > 0 && (
                <span>{formatDuration(assignment.duration_seconds)}</span>
              )}
              {assignment.changed_files && assignment.changed_files.length > 0 && (
                <span>{assignment.changed_files.length} files changed</span>
              )}
            </div>
          )}

          {/* Error message */}
          {assignment.error_message && (
            <div className="mt-1.5 text-[11px] text-rose-500 truncate" title={assignment.error_message}>
              {assignment.error_message}
            </div>
          )}
        </div>

        {/* Status badge */}
        <span
          className={classNames(
            "text-[11px] px-2 py-1 rounded-lg border font-medium flex-shrink-0",
            statusBg(status)
          )}
        >
          {status}
        </span>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

type TabId = "progress" | "agents" | "pending" | "decisions";

export function WorkflowTab({ groupId, isDark, onNavigateToActor }: WorkflowTabProps) {
  const { t } = useTranslation("layout");
  const {
    pendingSuggestions,
    decisions,
    progress,
    assignments,
    isLoading,
    error,
    refreshPending,
    refreshProgress,
    processBatch,
    clearWorkflow,
  } = useWorkflowStore();

  const [activeTab, setActiveTab] = useState<TabId>("progress");

  // Refresh on mount and periodically
  useEffect(() => {
    refreshPending();
    refreshProgress(groupId);

    const interval = setInterval(() => {
      refreshProgress(groupId, progress?.workflow_id);
      if (pendingSuggestions.length > 0 || progress?.status === "running") {
        refreshPending();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [groupId, refreshPending, refreshProgress, progress?.status, progress?.workflow_id, pendingSuggestions.length]);

  // Calculate stats
  const stats = useMemo(() => {
    const tasks = progress?.tasks || { total: 0, completed: 0, failed: 0, running: 0, pending: 0 };
    const progressPct = tasks.total > 0 ? Math.round((tasks.completed / tasks.total) * 100) : 0;
    return { ...tasks, progressPct };
  }, [progress]);

  // Group assignments by status for the agents tab
  const assignmentsByStatus = useMemo(() => {
    const running: WorkflowAgentAssignment[] = [];
    const pending: WorkflowAgentAssignment[] = [];
    const completed: WorkflowAgentAssignment[] = [];
    const failed: WorkflowAgentAssignment[] = [];

    for (const a of assignments) {
      switch (a.status) {
        case "running":
          running.push(a);
          break;
        case "completed":
          completed.push(a);
          break;
        case "failed":
          failed.push(a);
          break;
        default:
          pending.push(a);
      }
    }
    return { running, pending, completed, failed };
  }, [assignments]);

  // Model usage summary
  const modelUsage = useMemo(() => {
    const map = new Map<string, { runtime: string; model_id: string; count: number; completed: number; totalDuration: number }>();
    for (const a of assignments) {
      const key = `${a.model_runtime}:${a.model_id}`;
      const existing = map.get(key);
      if (existing) {
        existing.count++;
        if (a.status === "completed") existing.completed++;
        existing.totalDuration += a.duration_seconds || 0;
      } else {
        map.set(key, {
          runtime: a.model_runtime,
          model_id: a.model_id,
          count: 1,
          completed: a.status === "completed" ? 1 : 0,
          totalDuration: a.duration_seconds || 0,
        });
      }
    }
    return Array.from(map.values());
  }, [assignments]);

  const handleProcess = async (suggestionId: string) => {
    await processBatch(groupId, suggestionId);
  };

  const handleClear = async (workflowId: string) => {
    if (confirm("Clear workflow state? This cannot be undone.")) {
      await clearWorkflow(workflowId);
    }
  };

  const tabConfig: { id: TabId; label: string; badge?: number }[] = [
    { id: "progress", label: t("workflowProgress", "Progress") },
    { id: "agents", label: t("workflowAgents", "Agents"), badge: assignments.length },
    { id: "pending", label: t("workflowPending", "Pending"), badge: pendingSuggestions.length },
    { id: "decisions", label: t("workflowDecisions", "Decisions"), badge: decisions.length },
  ];

  return (
    <div className="flex-1 min-h-0 overflow-auto p-5">
      <div className="mx-auto max-w-5xl">
        {/* Header */}
        <div className="mb-6">
          <div className="text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
            Ralph Workflow
          </div>
          <div className="mt-2 text-xl font-semibold text-[var(--color-text-primary)]">
            {t("workflowDashboard", "Orchestration Dashboard")}
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <div className="glass-card rounded-xl p-4">
            <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wide">
              {t("workflowStatus", "Status")}
            </div>
            <div className={classNames(
              "mt-1 text-lg font-semibold",
              progress?.status === "running" ? "text-emerald-500" : "text-slate-500"
            )}>
              {progress?.status === "running" ? t("workflowRunning", "Running") : t("workflowIdle", "Idle")}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wide">
              {t("workflowTaskProgress", "Tasks")}
            </div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {stats.completed}/{stats.total}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wide">
              {t("workflowAgentsCount", "Agents")}
            </div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {assignmentsByStatus.running.length} / {assignments.length}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wide">
              {t("workflowBatches", "Batches")}
            </div>
            <div className="mt-1 text-lg font-semibold text-[var(--color-text-primary)]">
              {progress?.batches?.completed || 0}/{progress?.batches?.total || 0}
            </div>
          </div>
          <div className="glass-card rounded-xl p-4">
            <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-wide">
              {t("workflowDuration", "Duration")}
            </div>
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
                {progress.workflow_id?.slice(0, 16)}...
              </span>
              <span className="text-xs text-[var(--color-text-muted)]">
                {stats.progressPct}%
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
        <div className="flex gap-2 mb-4 overflow-x-auto scrollbar-hide">
          {tabConfig.map(({ id, label, badge }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={classNames(
                "px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap flex items-center gap-1.5",
                activeTab === id
                  ? "bg-cyan-500/20 text-cyan-600 dark:text-cyan-400 border border-cyan-500/30"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-tertiary)]"
              )}
            >
              {label}
              {badge != null && badge > 0 && (
                <span className={classNames(
                  "text-[10px] px-1.5 py-0.5 rounded-full font-bold",
                  activeTab === id
                    ? "bg-cyan-500/30 text-cyan-700 dark:text-cyan-300"
                    : "bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]"
                )}>
                  {badge}
                </span>
              )}
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

        {/* ─── Progress Tab ─── */}
        {!isLoading && activeTab === "progress" && (
          <div className="space-y-4">
            {/* Model Usage Summary */}
            {modelUsage.length > 0 && (
              <div className="glass-card rounded-xl p-4">
                <div className="text-sm font-medium text-[var(--color-text-primary)] mb-3">
                  {t("workflowModelUsage", "Model Usage")}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {modelUsage.map((mu) => {
                    const rc = getRuntimeColor(mu.runtime, isDark);
                    return (
                      <div
                        key={`${mu.runtime}:${mu.model_id}`}
                        className={classNames("px-3 py-2 rounded-lg border text-xs", rc.bg, rc.border)}
                      >
                        <div className={classNames("font-medium", rc.text)}>
                          {runtimeLabel(mu.runtime)}
                        </div>
                        <div className="text-[var(--color-text-muted)] mt-0.5">
                          {mu.model_id || "default"}
                          {" · "}{mu.completed}/{mu.count} done
                          {mu.totalDuration > 0 && ` · ${formatDuration(mu.totalDuration)}`}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Recent Events */}
            <div className="glass-card rounded-xl p-4">
              <div className="text-sm font-medium text-[var(--color-text-primary)] mb-3">
                {t("workflowRecentEvents", "Recent Events")}
              </div>
              {(!progress?.recent_events || progress.recent_events.length === 0) ? (
                <div className="text-sm text-[var(--color-text-muted)] py-4 text-center">
                  {t("workflowNoEvents", "No recent events")}
                </div>
              ) : (
                <div className="space-y-2">
                  {progress.recent_events.slice().reverse().map((event, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-3 p-2 rounded-lg bg-[var(--color-bg-secondary)]"
                    >
                      <span className="text-xs text-[var(--color-text-muted)] tabular-nums flex-shrink-0">
                        {formatTime(event.timestamp)}
                      </span>
                      <span className={classNames(
                        "text-xs font-medium px-2 py-0.5 rounded flex-shrink-0",
                        event.type === "batch_started" ? "bg-sky-500/20 text-sky-600 dark:text-sky-400" :
                        event.type === "task_completed" ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" :
                        event.type === "task_failed" ? "bg-rose-500/20 text-rose-600 dark:text-rose-400" :
                        event.type === "batch_completed" ? "bg-purple-500/20 text-purple-600 dark:text-purple-400" :
                        "bg-slate-500/20 text-slate-600 dark:text-slate-400"
                      )}>
                        {event.type.replace(/_/g, " ")}
                      </span>
                      {event.agent_name && (
                        <span className="text-xs text-[var(--color-text-secondary)] truncate">
                          {event.agent_name}
                        </span>
                      )}
                      {String(event.task_id ?? "") && (
                        <span className="text-xs text-[var(--color-text-muted)] truncate">
                          {String(event.task_id)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── Agents Tab ─── */}
        {!isLoading && activeTab === "agents" && (
          <div className="space-y-4">
            {assignments.length === 0 ? (
              <div className="glass-card rounded-xl p-8 text-center text-[var(--color-text-muted)]">
                {t("workflowNoAgents", "No agent assignments in current workflow")}
              </div>
            ) : (
              <>
                {/* Running */}
                {assignmentsByStatus.running.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-sky-500 mb-2 px-1">
                      Running ({assignmentsByStatus.running.length})
                    </div>
                    <div className="space-y-2">
                      {assignmentsByStatus.running.map((a) => (
                        <AssignmentCard
                          key={a.task_id}
                          assignment={a}
                          isDark={isDark}
                          onNavigateToActor={onNavigateToActor}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Pending */}
                {assignmentsByStatus.pending.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-amber-500 mb-2 px-1">
                      Pending ({assignmentsByStatus.pending.length})
                    </div>
                    <div className="space-y-2">
                      {assignmentsByStatus.pending.map((a) => (
                        <AssignmentCard
                          key={a.task_id}
                          assignment={a}
                          isDark={isDark}
                          onNavigateToActor={onNavigateToActor}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Completed */}
                {assignmentsByStatus.completed.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-emerald-500 mb-2 px-1">
                      Completed ({assignmentsByStatus.completed.length})
                    </div>
                    <div className="space-y-2">
                      {assignmentsByStatus.completed.map((a) => (
                        <AssignmentCard
                          key={a.task_id}
                          assignment={a}
                          isDark={isDark}
                          onNavigateToActor={onNavigateToActor}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Failed */}
                {assignmentsByStatus.failed.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-rose-500 mb-2 px-1">
                      Failed ({assignmentsByStatus.failed.length})
                    </div>
                    <div className="space-y-2">
                      {assignmentsByStatus.failed.map((a) => (
                        <AssignmentCard
                          key={a.task_id}
                          assignment={a}
                          isDark={isDark}
                          onNavigateToActor={onNavigateToActor}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ─── Pending Tab ─── */}
        {!isLoading && activeTab === "pending" && (
          <div className="space-y-4">
            {pendingSuggestions.length === 0 ? (
              <div className="glass-card rounded-xl p-8 text-center text-[var(--color-text-muted)]">
                {t("workflowNoPending", "No pending batch suggestions")}
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
                        {suggestion.suggestion_id.slice(0, 8)} · {suggestion.tasks.length} tasks · parallelism {suggestion.estimated_parallelism}
                      </div>
                    </div>
                    <button
                      onClick={() => handleProcess(suggestion.suggestion_id)}
                      className="px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium rounded-lg transition-colors"
                    >
                      {t("workflowProcess", "Process")}
                    </button>
                  </div>
                  {suggestion.rationale && (
                    <div className="text-xs text-[var(--color-text-secondary)] mb-3">
                      {suggestion.rationale}
                    </div>
                  )}
                  {/* Task list with type badges */}
                  <div className="space-y-1.5">
                    {suggestion.tasks.map((task) => (
                      <div
                        key={task.id}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--color-bg-secondary)]"
                      >
                        <span className={classNames(
                          "w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold flex-shrink-0",
                          taskTypeBg(task.type)
                        )}>
                          {taskTypeIcon(task.type)}
                        </span>
                        <span className="text-sm text-[var(--color-text-primary)] flex-1 min-w-0 truncate">
                          {task.title}
                        </span>
                        <span className="text-[11px] text-[var(--color-text-muted)] flex-shrink-0">
                          {task.type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ─── Decisions Tab ─── */}
        {!isLoading && activeTab === "decisions" && (
          <div className="space-y-4">
            {decisions.length === 0 ? (
              <div className="glass-card rounded-xl p-8 text-center text-[var(--color-text-muted)]">
                {t("workflowNoDecisions", "No decisions yet")}
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
                        {decision.decision_id.slice(0, 12)} · {new Date(decision.created_at).toLocaleString()}
                      </div>
                    </div>
                    <button
                      onClick={() => handleClear(decision.workflow_id)}
                      className="px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-rose-500 transition-colors"
                    >
                      {t("workflowClear", "Clear")}
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
