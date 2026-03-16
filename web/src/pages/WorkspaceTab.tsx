import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import * as api from "../services/api";
import { getWorkspaceGroupState, useGroupStore, useWorkspaceStore } from "../stores";
import type { WorkspaceFile } from "../types";
import { classNames } from "../utils/classNames";
import { MarkdownRenderer } from "../components/MarkdownRenderer";
import { EditIcon } from "../components/Icons";

type WorkspaceTabProps = {
  file: WorkspaceFile | null;
  loading: boolean;
  isDark: boolean;
};

function isMarkdownFile(file: WorkspaceFile | null): boolean {
  const name = String(file?.name || "").toLowerCase();
  const mime = String(file?.mime_type || "").toLowerCase();
  return mime.includes("markdown") || [".md", ".mdx", ".markdown"].some((suffix) => name.endsWith(suffix));
}

function isJsonFile(file: WorkspaceFile | null): boolean {
  const name = String(file?.name || "").toLowerCase();
  const mime = String(file?.mime_type || "").toLowerCase();
  return mime.includes("json") || name.endsWith(".json");
}

function isImageFile(file: WorkspaceFile | null): boolean {
  return String(file?.mime_type || "").toLowerCase().startsWith("image/");
}

function isPdfFile(file: WorkspaceFile | null): boolean {
  const name = String(file?.name || "").toLowerCase();
  const mime = String(file?.mime_type || "").toLowerCase();
  return mime === "application/pdf" || name.endsWith(".pdf");
}

function formatTextContent(file: WorkspaceFile | null): string {
  const content = String(file?.content || "");
  if (!isJsonFile(file)) return content;
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}

function ToolbarButton({
  active,
  children,
  disabled,
  href,
  onClick,
}: {
  active?: boolean;
  children: ReactNode;
  disabled?: boolean;
  href?: string;
  onClick?: () => void;
}) {
  const className = classNames(
    "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-all",
    active
      ? "bg-[var(--glass-accent-bg)] text-[var(--color-text-primary)]"
      : "glass-btn text-[var(--color-text-secondary)]",
    disabled ? "opacity-40" : ""
  );
  if (href) {
    return (
      <a href={href} download className={className}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" className={className} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

export function WorkspaceTab({ file, loading, isDark }: WorkspaceTabProps) {
  const { t } = useTranslation("layout");
  const selectedGroupId = useGroupStore((state) => state.selectedGroupId);
  const workspaceState = useWorkspaceStore((state) => getWorkspaceGroupState(selectedGroupId, state.byGroup));
  const saveFile = useWorkspaceStore((state) => state.saveFile);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState("");

  const rawContent = String(file?.content || "");
  const previewContent = useMemo(() => formatTextContent(file), [file]);
  const canEdit = Boolean(selectedGroupId && file?.is_text && !file?.truncated);
  const hasUnsaved = isEditing && draft !== rawContent;
  const downloadUrl = useMemo(() => {
    if (!selectedGroupId || !file) return "";
    return api.workspaceFileDownloadUrl(selectedGroupId, file.rel_path);
  }, [file, selectedGroupId]);

  useEffect(() => {
    setDraft(rawContent);
    setIsEditing(false);
    setLocalError("");
  }, [file?.path, rawContent]);

  async function handleSave(): Promise<void> {
    if (!selectedGroupId || !file) return;
    setLocalError("");
    try {
      await saveFile(selectedGroupId, { path: file.rel_path, content: draft });
      setIsEditing(false);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : t("workspaceSaveFailed"));
    }
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className={isDark ? "text-slate-500 text-sm" : "text-gray-500 text-sm"}>
          {t("workspaceLoading")}
        </span>
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className={isDark ? "text-slate-500 text-sm" : "text-gray-500 text-sm"}>
          {t("workspaceSelectFile")}
        </span>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-auto p-5">
      <div className="mx-auto max-w-5xl">
        <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">{t("workspacePreview")}</div>
            <div className="mt-2 text-xl font-semibold text-[var(--color-text-primary)]">{file.name}</div>
            <div className="mt-1 text-xs text-[var(--color-text-muted)]">
              {file.rel_path} · {file.mime_type} · {file.size_bytes} bytes
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {downloadUrl ? <ToolbarButton href={downloadUrl}>{t("workspaceDownload")}</ToolbarButton> : null}
            {canEdit && !isEditing ? (
              <ToolbarButton onClick={() => setIsEditing(true)}>
                <EditIcon size={14} />
                {t("workspaceEdit")}
              </ToolbarButton>
            ) : null}
            {isEditing ? (
              <>
                <ToolbarButton active onClick={() => void handleSave()} disabled={!hasUnsaved || workspaceState.savingFile}>
                  {workspaceState.savingFile ? t("workspaceSaving") : t("workspaceSave")}
                </ToolbarButton>
                <ToolbarButton onClick={() => {
                  setDraft(rawContent);
                  setIsEditing(false);
                  setLocalError("");
                }}>
                  {t("workspaceCancelEdit")}
                </ToolbarButton>
              </>
            ) : null}
          </div>
        </div>

        {file.truncated ? (
          <div className="mb-4 rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
            {t("workspaceTruncated")}
          </div>
        ) : null}
        {localError || workspaceState.error ? (
          <div className="mb-4 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-600 dark:text-rose-300">
            {localError || workspaceState.error}
          </div>
        ) : null}

        <div className="glass-card rounded-2xl overflow-hidden">
          {isEditing ? (
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className={classNames(
                "min-h-[60vh] w-full resize-y border-0 bg-transparent p-5 text-sm leading-6 outline-none",
                isDark ? "text-slate-200" : "text-gray-800"
              )}
              spellCheck={false}
            />
          ) : isImageFile(file) && downloadUrl ? (
            <div className="flex items-center justify-center p-5">
              <img src={downloadUrl} alt={file.name} className="max-h-[72vh] max-w-full rounded-xl object-contain" />
            </div>
          ) : isPdfFile(file) && downloadUrl ? (
            <iframe title={file.name} src={downloadUrl} className="h-[75vh] w-full border-0 bg-white" />
          ) : file.is_text && isMarkdownFile(file) ? (
            <div className="p-5">
              <MarkdownRenderer content={rawContent} isDark={isDark} />
            </div>
          ) : file.is_text ? (
            <pre
              className={classNames(
                "overflow-auto p-5 text-sm leading-6 whitespace-pre-wrap break-words",
                isDark ? "text-slate-200" : "text-gray-800"
              )}
            >
              {previewContent}
            </pre>
          ) : (
            <div className="space-y-4 p-5 text-sm text-[var(--color-text-secondary)]">
              <div>{t("workspaceBinaryFile")}</div>
              {downloadUrl ? (
                <div>
                  <a
                    href={downloadUrl}
                    download
                    className="inline-flex items-center rounded-xl bg-[var(--glass-accent-bg)] px-3 py-2 text-xs font-medium text-[var(--color-text-primary)]"
                  >
                    {t("workspaceDownload")}
                  </a>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
