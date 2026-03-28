import { useMemo } from "react";
import { DndContext } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useGroupStore } from "../../stores";
import { getWorkspaceGroupState, useWorkspaceStore } from "../../stores/useWorkspaceStore";
import type { WorkspaceEntry } from "../../types";

type BoardColumn = "planned" | "active" | "done";

const BOARD_COLUMNS: BoardColumn[] = ["planned", "active", "done"];

function getTaskColumn(status?: string): BoardColumn {
  const value = String(status || "").trim().toLowerCase();
  if (["done", "completed", "archived"].includes(value)) return "done";
  if (["active", "in_progress", "running", "blocked"].includes(value)) return "active";
  return "planned";
}

function getTaskTitle(task: WorkspaceEntry): string {
  return String(task.task?.title || "").trim() || task.name;
}

function getTaskKey(task: WorkspaceEntry): string {
  return String(task.task?.id || task.task?.task_ref || task.rel_path);
}

export function BoardTabContainer({ isDark: _isDark }: { isDark: boolean }) {
  const selectedGroupId = useGroupStore((state) => state.selectedGroupId);
  const tasks = useWorkspaceStore((state) => getWorkspaceGroupState(selectedGroupId, state.byGroup).tasks);
  const loadingTasks = useWorkspaceStore((state) => getWorkspaceGroupState(selectedGroupId, state.byGroup).loadingTasks);

  const columns = useMemo(() => {
    const next: Record<BoardColumn, WorkspaceEntry[]> = {
      planned: [],
      active: [],
      done: [],
    };
    for (const task of tasks) {
      next[getTaskColumn(task.task?.status)].push(task);
    }
    return next;
  }, [tasks]);
  const sortableIds = useMemo(
    () => ({
      planned: columns.planned.map(getTaskKey),
      active: columns.active.map(getTaskKey),
      done: columns.done.map(getTaskKey),
    }),
    [columns]
  );

  if (!selectedGroupId) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[var(--color-text-muted)]">Select a group to view the board.</div>;
  }

  if (loadingTasks && tasks.length === 0) {
    return <div className="flex flex-1 items-center justify-center text-sm text-[var(--color-text-muted)]">Loading board...</div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-5">
      <DndContext>
        <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">Board</div>
            <div className="mt-2 text-xl font-semibold text-[var(--color-text-primary)]">Workspace tasks</div>
          </div>
          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-3">
            {BOARD_COLUMNS.map((column) => (
              <section key={column} className="glass-card flex min-h-[18rem] flex-col rounded-2xl p-4">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-sm font-semibold capitalize text-[var(--color-text-primary)]">{column}</h2>
                  <span className="text-xs text-[var(--color-text-muted)]">{columns[column].length}</span>
                </div>
                <SortableContext items={sortableIds[column]} strategy={verticalListSortingStrategy}>
                  <div className="flex flex-1 flex-col gap-3">
                    {columns[column].length > 0 ? columns[column].map((task) => (
                      <article
                        key={getTaskKey(task)}
                        className="rounded-xl border border-[var(--glass-border)] bg-[var(--glass-panel)] px-4 py-3"
                      >
                        <div className="text-sm font-medium text-[var(--color-text-primary)]">{getTaskTitle(task)}</div>
                        <div className="mt-1 text-xs text-[var(--color-text-muted)]">{task.rel_path}</div>
                      </article>
                    )) : (
                      <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-[var(--glass-border)] text-sm text-[var(--color-text-muted)]">
                        No tasks
                      </div>
                    )}
                  </div>
                </SortableContext>
              </section>
            ))}
          </div>
        </div>
      </DndContext>
    </div>
  );
}
