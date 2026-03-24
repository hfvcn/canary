/**
 * ModelInfoCard - Display and edit model information
 *
 * Shows model details including:
 * - Display name and context window
 * - Strengths (as tags)
 * - User-editable description
 * - Foreman rating (if available)
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ModelInfo } from "../services/api";

interface ModelInfoCardProps {
  model: ModelInfo;
  onUpdateDescription?: (description: string, bestFor: string) => Promise<void>;
  onRequestRating?: () => void;
  onToggleEnabled?: (enabled: boolean) => Promise<void>;
  onDelete?: () => Promise<void>;
  readOnly?: boolean;
}

export function ModelInfoCard({
  model,
  onUpdateDescription,
  onRequestRating,
  onToggleEnabled,
  onDelete,
  readOnly = false,
}: ModelInfoCardProps) {
  const { t } = useTranslation("actors");
  const [editing, setEditing] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState(model.description || "");
  const [bestForDraft, setBestForDraft] = useState(model.best_for || "");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleToggleEnabled = async () => {
    if (!onToggleEnabled) return;
    setToggling(true);
    try {
      await onToggleEnabled(!(model.enabled ?? true));
    } finally {
      setToggling(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm(t("deleteModelConfirm", "Delete this custom model?"))) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const handleSave = async () => {
    if (!onUpdateDescription) return;
    setSaving(true);
    try {
      await onUpdateDescription(descriptionDraft, bestForDraft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDescriptionDraft(model.description || "");
    setBestForDraft(model.best_for || "");
    setEditing(false);
  };

  return (
    <div className="mt-3 rounded-xl border p-4 border-[var(--glass-border-subtle)] bg-[var(--glass-bg)]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-[var(--color-text-primary)]">
            {model.display_name}
          </span>
          {model.is_custom && (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-purple-500/10 text-purple-600 dark:text-purple-400">
              {t("customModel", "Custom")}
            </span>
          )}
          {model.enabled === false && (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-500/10 text-gray-500">
              {t("modelDisabled", "Hidden")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="text-xs px-2 py-0.5 rounded-full bg-[var(--glass-tab-bg)] text-[var(--color-text-muted)]">
            {model.context_window || "128k"}
          </div>
          {!readOnly && onToggleEnabled && (
            <button
              onClick={handleToggleEnabled}
              disabled={toggling}
              title={model.enabled !== false ? t("hideModel", "Hide from picker") : t("showModel", "Show in picker")}
              className={`p-1 rounded hover:bg-[var(--glass-tab-bg-hover)] transition-colors ${
                toggling ? "opacity-50" : ""
              }`}
            >
              {model.enabled !== false ? (
                <svg className="w-4 h-4 text-[var(--color-text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              ) : (
                <svg className="w-4 h-4 text-[var(--color-text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              )}
            </button>
          )}
          {!readOnly && model.is_custom && onDelete && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              title={t("deleteModel", "Delete custom model")}
              className={`p-1 rounded hover:bg-red-500/10 transition-colors ${
                deleting ? "opacity-50" : ""
              }`}
            >
              <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Strengths */}
      {model.strengths && model.strengths.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {model.strengths.map((s) => (
            <span
              key={s}
              className="px-2 py-0.5 rounded-full text-xs bg-green-500/10 text-green-600 dark:text-green-400"
            >
              {s.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* Weaknesses */}
      {model.weaknesses && model.weaknesses.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {model.weaknesses.map((w) => (
            <span
              key={w}
              className="px-2 py-0.5 rounded-full text-xs bg-red-500/10 text-red-600 dark:text-red-400"
            >
              {w.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* Description Section */}
      <div className="mt-3 pt-3 border-t border-[var(--glass-border-subtle)]">
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium text-[var(--color-text-muted)]">
            {t("modelDescription", "Description")}
          </label>
          {!readOnly && !editing && onUpdateDescription && (
            <button
              onClick={() => setEditing(true)}
              className="text-xs text-blue-500 hover:underline"
            >
              {t("edit", "Edit")}
            </button>
          )}
        </div>

        {editing ? (
          <div className="space-y-2">
            <textarea
              className="w-full rounded-lg border px-3 py-2 text-sm glass-input text-[var(--color-text-primary)]"
              rows={3}
              value={descriptionDraft}
              onChange={(e) => setDescriptionDraft(e.target.value)}
              placeholder={t("modelDescriptionPlaceholder", "Add a description for this model...")}
              disabled={saving}
            />
            <input
              className="w-full rounded-lg border px-3 py-2 text-sm glass-input text-[var(--color-text-primary)]"
              value={bestForDraft}
              onChange={(e) => setBestForDraft(e.target.value)}
              placeholder={t("modelBestForPlaceholder", "Best for: backend, frontend, etc.")}
              disabled={saving}
            />
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? t("saving", "Saving...") : t("save", "Save")}
              </button>
              <button
                onClick={handleCancel}
                disabled={saving}
                className="px-3 py-1.5 text-sm border border-[var(--glass-border-subtle)] rounded-lg hover:bg-[var(--glass-tab-bg-hover)]"
              >
                {t("cancel", "Cancel")}
              </button>
            </div>
          </div>
        ) : (
          <div>
            {model.description ? (
              <p className="text-sm text-[var(--color-text-secondary)]">{model.description}</p>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] italic">
                {t("noDescription", "No description yet")}
              </p>
            )}
            {model.best_for && (
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                <span className="font-medium">{t("bestFor", "Best for")}:</span> {model.best_for}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Foreman Comment Section */}
      <div className="mt-3 pt-3 border-t border-[var(--glass-border-subtle)]">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-[var(--color-text-muted)]">
            {t("foremanComment", "Foreman Comment")}
          </div>
          {!readOnly && onRequestRating && !model.foreman_notes && (
            <button
              onClick={onRequestRating}
              className="text-xs text-blue-500 hover:underline"
            >
              {t("refreshComment", "Refresh")}
            </button>
          )}
        </div>

        {model.foreman_notes ? (
          <div className="mt-1">
            <p className="text-sm text-[var(--color-text-secondary)]">
              {model.foreman_notes}
            </p>
            <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              {model.foreman_sample_count != null && model.foreman_sample_count > 0 && (
                <span>{t("basedOnTasks", "Based on {{count}} task(s)", { count: model.foreman_sample_count })}</span>
              )}
              {model.last_rated_at && (
                <span>· {new Date(model.last_rated_at).toLocaleDateString()}</span>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-1 text-xs text-[var(--color-text-muted)] italic">
            {t("noCommentYet", "No comment yet. Complete tasks with this model to receive Foreman's feedback.")}
          </p>
        )}
      </div>
    </div>
  );
}
