import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { WorkspaceEntry } from "../types";
import { classNames } from "../utils/classNames";

type BoardTabProps = {
  tasks: WorkspaceEntry[];
  loading: boolean;
  isDark: boolean;
  onOpenTask: (path: string) => void;
};

function tone(status: string): string {
  const value = String(status || "").trim().toLowerCase();
  if (value === "done" || value === "archived") return "border-emerald-500/20 bg-emerald-500/8 text-emerald-600";
  if (value === "blocked") return "border-rose-500/20 bg-rose-500/8 text-rose-600";
  if (value === "in_progress" || value === "active") return "border-sky-500/20 bg-sky-500/8 text-sky-600";
  return "border-amber-500/20 bg-amber-500/8 text-amber-700";
}

export function BoardTab({ tasks, loading, isDark, onOpenTask }: BoardTabProps) {
  const { t } = useTranslation("layout");

  const grouped = useMemo(() => {
    const buckets: Record<string, WorkspaceEntry[]> = {
      todo: [],
      in_progress: [],
      blocked: [],
      done: [],
    };
    for (const item of tasks) {
      const raw = String(item.task?.status || "todo").trim().toLowerCase();
      const key = raw in buckets ? raw : "todo";
      buckets[key].push(item);
    }
    return buckets;
  }, [tasks]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className={isDark ? "text-slate-500 text-sm" : "text-gray-500 text-sm"}>
          {t("workspaceLoading")}
        </span>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-auto p-5">
      <div className="mx-auto max-w-6xl">
        <div className="mb-4">
          <div className="text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">{t("board")}</div>
          <div className="mt-2 text-xl font-semibold text-[var(--color-text-primary)]">{t("workspaceTasks")}</div>
        </div>

        {tasks.length === 0 ? (
          <div className="glass-card rounded-2xl p-8 text-sm text-[var(--color-text-secondary)]">{t("boardEmpty")}</div>
        ) : null}

        {tasks.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-4">
            {(["todo", "in_progress", "blocked", "done"] as const).map((status) => (
              <div key={status} className="glass-card rounded-2xl p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-sm font-semibold text-[var(--color-text-primary)]">{status}</div>
                  <div className="text-xs text-[var(--color-text-muted)]">{grouped[status].length}</div>
                </div>
                <div className="space-y-3">
                  {grouped[status].map((task) => (
                    <button
                      key={task.rel_path}
                      type="button"
                      className={classNames(
                        "w-full rounded-xl border p-3 text-left transition-all hover:-translate-y-0.5",
                        tone(String(task.task?.status || status))
                      )}
                      onClick={() => onOpenTask(task.rel_path)}
                    >
                      <div className="text-sm font-medium">{task.task?.title || task.name}</div>
                      <div className="mt-1 text-[11px] opacity-80">{task.rel_path}</div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
