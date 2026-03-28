/**
 * WorkflowActivityBar — Compact workflow status strip for the Chat tab.
 *
 * Shows active agent assignments, task progress, and model info inline
 * so users don't need to switch to the Workflow tab for status updates.
 */
import { useEffect, useMemo, useState } from "react";
import { useWorkflowStore } from "../stores/useWorkflowStore";
import type { WorkflowAgentAssignment } from "../stores/useWorkflowStore";
import { classNames } from "../utils/classNames";
import { getRuntimeColor, RUNTIME_INFO } from "../types";

type WorkflowActivityBarProps = {
  groupId: string;
  isDark: boolean;
  onNavigateToAgent?: (actorId: string) => void;
  onNavigateToWorkflow?: () => void;
};

function runtimeLabel(runtime: string): string {
  return RUNTIME_INFO[runtime]?.label || runtime || "";
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m${s}s` : `${m}m`;
}

function statusDot(status: string): string {
  switch (status) {
    case "running":
      return "bg-sky-500 shadow-[0_0_6px_rgba(14,165,233,0.4)]";
    case "completed":
      return "bg-emerald-500";
    case "failed":
      return "bg-rose-500";
    case "stalled":
      return "bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.35)]";
    case "offline":
      return "bg-slate-400";
    case "blocked":
      return "bg-rose-500 shadow-[0_0_0_1px_rgba(244,63,94,0.3)]";
    default:
      return "bg-amber-500/70";
  }
}

function chipStatusClass(status: string, isDark: boolean): string {
  switch (status) {
    case "stalled":
      return isDark
        ? "bg-amber-950/30 border-amber-700/60 text-amber-200"
        : "bg-amber-50 border-amber-300 text-amber-900";
    case "offline":
      return isDark
        ? "bg-slate-900/50 border-slate-700 text-slate-300"
        : "bg-slate-100 border-slate-300 text-slate-700";
    case "blocked":
      return isDark
        ? "border-rose-500/70 shadow-[inset_0_0_0_1px_rgba(244,63,94,0.25)]"
        : "border-rose-400 shadow-[inset_0_0_0_1px_rgba(248,113,113,0.2)]";
    default:
      return "";
  }
}

function AgentChip({
  assignment,
  isDark,
  onClick,
}: {
  assignment: WorkflowAgentAssignment;
  isDark: boolean;
  onClick?: () => void;
}) {
  const rc = getRuntimeColor(assignment.model_runtime, isDark);
  const status = assignment.status || "pending";
  const chipClass = chipStatusClass(status, isDark);
  const nameClass = status === "stalled" || status === "offline" ? "" : rc.text;

  return (
    <button
      onClick={onClick}
      className={classNames(
        "flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] border transition-colors",
        "hover:brightness-110 cursor-pointer",
        rc.bg,
        rc.border,
        chipClass
      )}
      title={`${assignment.task_title}\n${runtimeLabel(assignment.model_runtime)} · ${assignment.model_id || "default"}\nStatus: ${status}`}
    >
      <span className={classNames("w-1.5 h-1.5 rounded-full flex-shrink-0", statusDot(status))} />
      <span className={classNames("font-medium truncate max-w-[100px]", nameClass)}>
        {assignment.agent_name || assignment.agent_id}
      </span>
      <span className="text-[var(--color-text-muted)] truncate max-w-[120px]">
        {assignment.task_title}
      </span>
      {status === "completed" && assignment.duration_seconds != null && assignment.duration_seconds > 0 && (
        <span className="text-emerald-500 flex-shrink-0">{formatDuration(assignment.duration_seconds)}</span>
      )}
    </button>
  );
}

export function WorkflowActivityBar({
  groupId,
  isDark,
  onNavigateToAgent,
  onNavigateToWorkflow,
}: WorkflowActivityBarProps) {
  const {
    progress,
    assignments,
    refreshProgress,
  } = useWorkflowStore();

  const [collapsed, setCollapsed] = useState(false);

  // Poll progress (skip if no group selected)
  useEffect(() => {
    if (!groupId) return;
    refreshProgress(groupId);
    const interval = setInterval(() => {
      refreshProgress(groupId);
    }, 5000);
    return () => clearInterval(interval);
  }, [groupId, refreshProgress]);

  // Categorize
  const { running, pending, completed, failed, total } = useMemo(() => {
    const r: WorkflowAgentAssignment[] = [];
    const p: WorkflowAgentAssignment[] = [];
    const c: WorkflowAgentAssignment[] = [];
    const f: WorkflowAgentAssignment[] = [];
    for (const a of assignments) {
      switch (a.status) {
        case "running": r.push(a); break;
        case "completed": c.push(a); break;
        case "failed": f.push(a); break;
        default: p.push(a);
      }
    }
    return { running: r, pending: p, completed: c, failed: f, total: assignments.length };
  }, [assignments]);

  // Don't render if no group or no workflow activity
  if (!groupId || !progress || progress.status === "idle" || total === 0) {
    return null;
  }

  const activeCount = running.length + pending.length;
  const doneCount = completed.length;

  return (
    <div
      className={classNames(
        "border-b transition-all",
        "border-[var(--glass-border-subtle)] bg-[var(--color-bg-secondary)]"
      )}
    >
      {/* Summary row — always visible */}
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Status indicator */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500" />
          </span>
          <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">
            Workflow
          </span>
        </div>

        {/* Counters */}
        <div className="flex items-center gap-2 text-[11px] text-[var(--color-text-muted)]">
          {running.length > 0 && (
            <span className="text-sky-500">{running.length} running</span>
          )}
          {pending.length > 0 && (
            <span className="text-amber-500">{pending.length} pending</span>
          )}
          {doneCount > 0 && (
            <span className="text-emerald-500">{doneCount}/{total} done</span>
          )}
          {failed.length > 0 && (
            <span className="text-rose-500">{failed.length} failed</span>
          )}
        </div>

        {/* Compact progress bar */}
        {total > 0 && (
          <div className="flex-1 min-w-[60px] max-w-[200px] h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-500"
              style={{ width: `${Math.round((doneCount / total) * 100)}%` }}
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
          {activeCount > 0 && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-[11px] px-2 py-0.5 rounded text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors"
            >
              {collapsed ? "Show" : "Hide"}
            </button>
          )}
          <button
            onClick={onNavigateToWorkflow}
            className="text-[11px] px-2 py-0.5 rounded text-cyan-600 dark:text-cyan-400 hover:bg-cyan-500/10 transition-colors"
          >
            Details
          </button>
        </div>
      </div>

      {/* Agent chips — collapsible */}
      {!collapsed && (running.length > 0 || pending.length > 0) && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {running.map((a) => (
            <AgentChip
              key={a.task_id}
              assignment={a}
              isDark={isDark}
              onClick={() => onNavigateToAgent?.(a.agent_id)}
            />
          ))}
          {pending.map((a) => (
            <AgentChip
              key={a.task_id}
              assignment={a}
              isDark={isDark}
              onClick={() => onNavigateToAgent?.(a.agent_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
