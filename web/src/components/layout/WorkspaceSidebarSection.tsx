import { type ChangeEvent, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { WorkspaceTree } from "../../types";
import { getWorkspaceGroupState, useGroupStore, useWorkspaceStore } from "../../stores";
import { classNames } from "../../utils/classNames";
import {
  ChevronLeftIcon,
  ClipboardIcon,
  FileIcon,
  FolderIcon,
  PlusIcon,
  RefreshIcon,
} from "../Icons";

type WorkspaceSidebarSectionProps = {
  isDark: boolean;
  tree: WorkspaceTree | null;
  selectedFilePath: string;
  loading: boolean;
  error: string;
  readOnly?: boolean;
  onRefresh: () => void;
  onOpenFolder: (path: string) => void;
  onOpenFile: (path: string) => void;
  onCreateFolder: (kind: "folder" | "task") => void;
  onCreateFile: () => void;
};

function taskStatusTone(status: string): string {
  const value = String(status || "").trim().toLowerCase();
  if (value === "done" || value === "archived") return "text-emerald-600 bg-emerald-500/10";
  if (value === "blocked") return "text-rose-600 bg-rose-500/10";
  if (value === "in_progress" || value === "active") return "text-sky-600 bg-sky-500/10";
  return "text-amber-700 bg-amber-500/10";
}

export function WorkspaceSidebarSection({
  isDark,
  tree,
  selectedFilePath,
  loading,
  error,
  readOnly,
  onRefresh,
  onOpenFolder,
  onOpenFile,
  onCreateFolder,
  onCreateFile,
}: WorkspaceSidebarSectionProps) {
  const { t } = useTranslation("layout");
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const selectedGroupId = useGroupStore((state) => state.selectedGroupId);
  const workspaceState = useWorkspaceStore((state) => getWorkspaceGroupState(selectedGroupId, state.byGroup));
  const uploadFiles = useWorkspaceStore((state) => state.uploadFiles);

  const breadcrumb = useMemo(() => {
    const relPath = String(tree?.rel_path || "").trim();
    if (!relPath) return t("workspaceRoot");
    return relPath;
  }, [t, tree?.rel_path]);

  async function handleUploadChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!selectedGroupId || files.length === 0) return;
    try {
      await uploadFiles(selectedGroupId, files);
    } catch {
      return;
    }
  }

  return (
    <div className="mt-4 border-t border-[var(--glass-border-subtle)] pt-4">
      <input
        ref={uploadInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => void handleUploadChange(event)}
      />
      <div className="flex items-center justify-between gap-2 px-2">
        <div className="flex items-center gap-2 min-w-0">
          <FolderIcon size={15} className="text-[var(--color-text-muted)]" />
          <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
            {t("workspace")}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="glass-btn rounded-lg p-1.5 text-[var(--color-text-muted)]"
            onClick={onRefresh}
            title={t("workspaceRefresh")}
            aria-label={t("workspaceRefresh")}
          >
            <RefreshIcon size={14} />
          </button>
          {!readOnly ? (
            <>
              <button
                type="button"
                className="glass-btn rounded-lg p-1.5 text-[var(--color-text-muted)]"
                onClick={() => onCreateFolder("task")}
                title={t("newTask")}
                aria-label={t("newTask")}
              >
                <ClipboardIcon size={14} />
              </button>
              <button
                type="button"
                className="glass-btn rounded-lg p-1.5 text-[var(--color-text-muted)]"
                onClick={() => onCreateFolder("folder")}
                title={t("newFolder")}
                aria-label={t("newFolder")}
              >
                <FolderIcon size={14} />
              </button>
              <button
                type="button"
                className="glass-btn rounded-lg p-1.5 text-[var(--color-text-muted)]"
                onClick={onCreateFile}
                title={t("newFile")}
                aria-label={t("newFile")}
              >
                <PlusIcon size={14} />
              </button>
              <button
                type="button"
                className="glass-btn rounded-lg px-2 py-1.5 text-[11px] text-[var(--color-text-muted)]"
                onClick={() => uploadInputRef.current?.click()}
                title={t("workspaceUpload")}
                aria-label={t("workspaceUpload")}
                disabled={workspaceState.uploadingFiles}
              >
                {workspaceState.uploadingFiles ? t("workspaceUploading") : t("workspaceUpload")}
              </button>
            </>
          ) : null}
        </div>
      </div>

      <div className="mt-3 px-2">
        <div className="glass-card rounded-xl p-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="glass-btn rounded-lg p-1.5 text-[var(--color-text-muted)] disabled:opacity-40"
              onClick={() => onOpenFolder(String(tree?.parent_rel_path || ""))}
              disabled={!tree || tree.parent_rel_path == null}
              title={t("workspaceUp")}
              aria-label={t("workspaceUp")}
            >
              <ChevronLeftIcon size={14} />
            </button>
            <div className="min-w-0 text-xs text-[var(--color-text-secondary)] truncate">{breadcrumb}</div>
          </div>

          {loading ? <div className="mt-3 text-xs text-[var(--color-text-muted)]">{t("workspaceLoading")}</div> : null}
          {!loading && error ? <div className="mt-3 text-xs text-rose-500 break-words">{error}</div> : null}
          {!loading && !error && !tree ? (
            <div className="mt-3 text-xs text-[var(--color-text-muted)]">{t("workspaceUnavailable")}</div>
          ) : null}

          {!loading && !error && tree ? (
            <div className="mt-3 space-y-1">
              {tree.items.length === 0 ? (
                <div className="text-xs text-[var(--color-text-muted)]">{t("workspaceNoFiles")}</div>
              ) : null}
              {tree.items.map((item) => {
                const isActive = item.rel_path === selectedFilePath;
                const isFolder = item.is_dir;
                const icon = item.kind === "task"
                  ? <ClipboardIcon size={14} className="text-amber-500" />
                  : isFolder
                    ? <FolderIcon size={14} className="text-cyan-500" />
                    : <FileIcon size={14} className="text-[var(--color-text-muted)]" />;
                return (
                  <button
                    key={item.rel_path || item.name}
                    type="button"
                    className={classNames(
                      "w-full rounded-xl px-2 py-2 text-left transition-all",
                      isActive ? "bg-[var(--glass-accent-bg)]" : "hover:bg-black/5 dark:hover:bg-white/5"
                    )}
                    onClick={() => (isFolder ? onOpenFolder(item.rel_path) : onOpenFile(item.rel_path))}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {icon}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-[var(--color-text-primary)]">{item.name}</div>
                        {item.kind === "task" ? (
                          <div className="mt-1 flex items-center gap-2">
                            <span className={classNames("rounded-full px-1.5 py-0.5 text-[10px]", taskStatusTone(String(item.task?.status || "")))}>
                              {String(item.task?.status || "planned")}
                            </span>
                          </div>
                        ) : (
                          <div className={classNames("text-[11px]", isDark ? "text-slate-500" : "text-gray-500")}>
                            {isFolder ? t("workspaceFolder") : t("workspaceFile")}
                          </div>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
