import { useState, useEffect } from "react";
import {
  ActorProfile,
  RuntimeInfo,
  SupportedRuntime,
  SUPPORTED_RUNTIMES,
  RUNTIME_INFO,
} from "../../types";
import { useTranslation } from "react-i18next";
import {
  BASIC_MCP_CONFIG_SNIPPET,
  COPILOT_MCP_CONFIG_SNIPPET,
  OPENCODE_MCP_CONFIG_SNIPPET,
} from "../../utils/mcpConfigSnippets";
import { classNames } from "../../utils/classNames";
import { useModalA11y } from "../../hooks/useModalA11y";
import { CapabilityPicker } from "../CapabilityPicker";
import { RolePresetPicker } from "../RolePresetPicker";
import { formatCapabilityIdInput, parseCapabilityIdInput } from "../../utils/capabilityAutoload";
import * as api from "../../services/api";
import type { ModelInfo } from "../../services/api";
import { ModelInfoCard } from "../ModelInfoCard";

export interface AddActorModalProps {
  isOpen: boolean;
  isDark: boolean;
  busy: string;
  hasForeman: boolean;
  runtimes: RuntimeInfo[];
  groupId: string;

  suggestedActorId: string;
  newActorId: string;
  setNewActorId: (id: string) => void;

  newActorRole: "peer" | "foreman";
  setNewActorRole: (role: "peer" | "foreman") => void;

  newActorUseProfile: boolean;
  setNewActorUseProfile: (v: boolean) => void;
  newActorProfileId: string;
  setNewActorProfileId: (id: string) => void;
  actorProfiles: ActorProfile[];
  actorProfilesBusy: boolean;

  newActorRuntime: SupportedRuntime;
  setNewActorRuntime: (runtime: SupportedRuntime) => void;

  newActorCommand: string;
  setNewActorCommand: (cmd: string) => void;
  newActorUseDefaultCommand: boolean;
  setNewActorUseDefaultCommand: (v: boolean) => void;

  newActorModelId: string;
  setNewActorModelId: (modelId: string) => void;

  newActorSecretsSetText: string;
  setNewActorSecretsSetText: (v: string) => void;
  newActorCapabilityAutoloadText: string;
  setNewActorCapabilityAutoloadText: (v: string) => void;
  newActorRoleNotes: string;
  setNewActorRoleNotes: (v: string) => void;

  showAdvancedActor: boolean;
  setShowAdvancedActor: (show: boolean) => void;

  addActorError: string;
  setAddActorError: (msg: string) => void;

  canAddActor: boolean;
  addActorDisabledReason: string;

  onAddActor: () => void;
  onSaveAsProfile: () => void;
  onClose: () => void;
  onCancelAndReset: () => void;
}

function commandPreview(command: string[] | undefined): string {
  const cmd = Array.isArray(command) ? command.filter((item) => typeof item === "string" && item.trim()) : [];
  return cmd.join(" ");
}

function modeButtonClass(selected: boolean): string {
  return [
    "px-3 py-2.5 rounded-xl border text-sm min-h-[44px] font-medium transition-colors",
    selected
      ? "bg-blue-600 text-white border-blue-600"
      : "border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-secondary)] hover:bg-[var(--glass-tab-bg-hover)]",
  ].join(" ");
}

export function AddActorModal({
  isOpen,
  isDark,
  busy,
  hasForeman,
  runtimes,
  groupId,
  suggestedActorId,
  newActorId,
  setNewActorId,
  newActorRole,
  setNewActorRole,
  newActorUseProfile,
  setNewActorUseProfile,
  newActorProfileId,
  setNewActorProfileId,
  actorProfiles,
  actorProfilesBusy,
  newActorRuntime,
  setNewActorRuntime,
  newActorCommand,
  setNewActorCommand,
  newActorUseDefaultCommand,
  setNewActorUseDefaultCommand,
  newActorModelId,
  setNewActorModelId,
  newActorSecretsSetText,
  setNewActorSecretsSetText,
  newActorCapabilityAutoloadText,
  setNewActorCapabilityAutoloadText,
  newActorRoleNotes,
  setNewActorRoleNotes,
  showAdvancedActor,
  setShowAdvancedActor,
  addActorError,
  setAddActorError,
  canAddActor,
  addActorDisabledReason,
  onAddActor,
  onSaveAsProfile,
  onClose,
  onCancelAndReset,
}: AddActorModalProps) {
  const { t } = useTranslation("actors");
  const { modalRef } = useModalA11y(isOpen, onClose);

  // Model selection state
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [showAddCustomModel, setShowAddCustomModel] = useState(false);
  const [customModelId, setCustomModelId] = useState("");
  const [addingCustomModel, setAddingCustomModel] = useState(false);
  const [editingModelKey, setEditingModelKey] = useState<string | null>(null);

  // Load models when runtime changes
  useEffect(() => {
    if (!isOpen) return;
    if (newActorUseProfile) {
      setModels([]);
      setNewActorModelId("");
      return;
    }
    if (!newActorRuntime || newActorRuntime === "custom") {
      setModels([]);
      setNewActorModelId("");
      return;
    }
    if (!["claude", "gemini", "codex"].includes(newActorRuntime)) {
      setModels([]);
      setNewActorModelId("");
      return;
    }

    setModelsBusy(true);
    api.fetchModelsByRuntime(newActorRuntime)
      .then((resp) => {
        const data = resp as unknown as { ok: boolean; models?: ModelInfo[]; result?: { models?: ModelInfo[] } };
        const modelList = data.models || data.result?.models || [];
        if (resp.ok && modelList.length > 0) {
          setModels(modelList);
        } else {
          setModels([]);
        }
      })
      .catch(() => {
        setModels([]);
      })
      .finally(() => {
        setModelsBusy(false);
      });
  }, [isOpen, newActorRuntime, newActorUseProfile, setNewActorModelId]);

  if (!isOpen) return null;

  const runtimeInfo = runtimes.find((r) => r.name === newActorRuntime);
  const runtimeAvailable = runtimeInfo?.available ?? false;
  const defaultCommand = runtimeInfo?.recommended_command || "";
  // Compute display command with model parameter when selected
  const displayCommand = (() => {
    if (!defaultCommand) return "";
    if (!newActorModelId) return defaultCommand;
    // Extract model_id from model_key (e.g., "claude-claude-sonnet-4-6" -> "claude-sonnet-4-6")
    const modelId = newActorModelId.startsWith(`${newActorRuntime}-`)
      ? newActorModelId.slice(newActorRuntime.length + 1)
      : newActorModelId;
    return `${defaultCommand} --model ${modelId}`;
  })();
  const selectedProfile = actorProfiles.find((item) => String(item.id || "") === String(newActorProfileId || ""));
  const selectedProfileRuntime = String(selectedProfile?.runtime || "").trim() as SupportedRuntime;
  const selectedProfileCommand = commandPreview(selectedProfile?.command);
  const showRuntimeSetup =
    !newActorUseProfile &&
    (newActorRuntime === "cursor" ||
      newActorRuntime === "kilocode" ||
      newActorRuntime === "opencode" ||
      newActorRuntime === "copilot" ||
      newActorRuntime === "custom");
  const showCommandEditor = !newActorUseProfile && (newActorRuntime === "custom" || !newActorUseDefaultCommand);

  const sectionCardClass = "rounded-2xl p-4 sm:p-5 glass-panel";
  const sectionTitleClass = "text-sm font-semibold text-[var(--color-text-primary)]";
  const sectionHintClass = "mt-1 text-xs text-[var(--color-text-muted)]";
  const collapsibleSummaryClass =
    "flex cursor-pointer list-none items-start justify-between gap-3 [&::-webkit-details-marker]:hidden";
  const collapsibleLabelClass = "text-xs font-medium text-[var(--color-text-secondary)]";
  const collapsibleChevronClass =
    "text-sm transition-transform group-open:rotate-180 text-[var(--color-text-tertiary)]";
  const nestedCardClass = "rounded-xl border p-3 border-[var(--glass-border-subtle)] bg-[var(--glass-bg)]";

  return (
    <div
      className="fixed inset-0 backdrop-blur-sm flex items-stretch sm:items-start justify-center p-0 sm:p-6 z-50 animate-fade-in glass-overlay"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-actor-title"
    >
      <div
        ref={modalRef}
        className="w-full h-full sm:h-auto sm:max-w-2xl sm:mt-10 sm:max-h-[calc(100vh-5rem)] border border-[var(--glass-border-subtle)] shadow-2xl animate-scale-in rounded-none sm:rounded-2xl glass-modal flex flex-col overflow-hidden text-[var(--color-text-primary)]"
      >
        <div className="px-6 py-4 border-b safe-area-inset-top border-[var(--glass-border-subtle)] glass-header flex-shrink-0">
          <div id="add-actor-title" className="text-lg font-semibold text-[var(--color-text-primary)]">
            {t("addAiAgent")}
          </div>
          <div className="text-sm mt-1 text-[var(--color-text-muted)]">{t("addActorSubtitle")}</div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 safe-area-bottom-compact">
          <div className="mx-auto max-w-2xl space-y-4">
            <section className={sectionCardClass}>
              <div className={sectionTitleClass}>{t("sectionBasics")}</div>
              <div className={sectionHintClass}>{t("addSectionBasicsHint")}</div>

              <div className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">
                    {t("agentName")} <span className="text-[var(--color-text-muted)]">{t("unicodeSupport")}</span>
                  </label>
                  <input
                    className="w-full rounded-xl border px-4 py-2.5 text-sm min-h-[44px] transition-colors glass-input text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)]"
                    value={newActorId}
                    onChange={(e) => setNewActorId(e.target.value)}
                    placeholder={suggestedActorId}
                  />
                  <div className="text-[10px] mt-1.5 text-[var(--color-text-muted)]">
                    {t("leaveEmptyToUse")}{" "}
                    <code className="px-1 rounded bg-[var(--glass-tab-bg)] text-[var(--color-text-secondary)]">
                      {suggestedActorId}
                    </code>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">{t("role")}</label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <button
                      type="button"
                      className={classNames(
                        "px-4 py-2.5 rounded-xl border text-sm font-medium transition-all min-h-[44px]",
                        newActorRole === "foreman"
                          ? "bg-amber-500/20 border-amber-500 text-amber-700 dark:text-amber-300"
                          : hasForeman
                            ? "border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-muted)] cursor-not-allowed"
                            : "border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-secondary)] hover:bg-[var(--glass-tab-bg-hover)]"
                      )}
                      onClick={() => {
                        if (!hasForeman) setNewActorRole("foreman");
                      }}
                      disabled={hasForeman}
                    >
                      {t("foremanRole")} {hasForeman && t("foremanExists")}
                    </button>
                    <button
                      type="button"
                      className={classNames(
                        "px-4 py-2.5 rounded-xl border text-sm font-medium transition-all min-h-[44px]",
                        newActorRole === "peer"
                          ? "bg-blue-500/20 border-blue-500 text-blue-700 dark:text-blue-300"
                          : !hasForeman
                            ? "border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-muted)] cursor-not-allowed"
                            : "border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-secondary)] hover:bg-[var(--glass-tab-bg-hover)]"
                      )}
                      onClick={() => {
                        if (hasForeman) setNewActorRole("peer");
                      }}
                      disabled={!hasForeman}
                    >
                      {t("peerRole")} {!hasForeman && t("needForemanFirst")}
                    </button>
                  </div>
                  <div className="text-[10px] mt-1.5 text-[var(--color-text-muted)]">
                    {hasForeman ? t("foremanLeads") : t("firstAgentForeman")}
                  </div>
                </div>

                <RolePresetPicker
                  draftValue={newActorRoleNotes}
                  onChangeDraft={setNewActorRoleNotes}
                  disabled={busy === "actor-add"}
                />

                <div>
                  <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">{t("roleNotes")}</label>
                  <textarea
                    className="w-full rounded-xl border px-3 py-2 text-sm min-h-[144px] transition-colors glass-input text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)]"
                    value={newActorRoleNotes}
                    onChange={(e) => setNewActorRoleNotes(e.target.value)}
                    placeholder={t("roleNotesPlaceholder")}
                    spellCheck={false}
                  />
                  <div className="text-[10px] mt-1.5 text-[var(--color-text-muted)]">{t("newActorRoleNotesHint")}</div>
                </div>
              </div>
            </section>

            <section className={sectionCardClass}>
              <div className={sectionTitleClass}>{t("sectionRuntime")}</div>
              <div className={sectionHintClass}>{t("sectionRuntimeHint")}</div>

              <div className="mt-4">
                <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">{t("creationMode")}</label>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" className={modeButtonClass(!newActorUseProfile)} onClick={() => setNewActorUseProfile(false)}>
                    {t("customAgent")}
                  </button>
                  <button type="button" className={modeButtonClass(newActorUseProfile)} onClick={() => setNewActorUseProfile(true)}>
                    {t("fromActorProfile")}
                  </button>
                </div>
              </div>

              <div className="mt-4 space-y-4">
                {newActorUseProfile ? (
                  <>
                    <div>
                      <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">{t("actorProfile")}</label>
                      <select
                        className="w-full rounded-xl border px-4 py-2.5 text-sm min-h-[44px] transition-colors glass-input text-[var(--color-text-primary)]"
                        value={newActorProfileId}
                        onChange={(e) => setNewActorProfileId(e.target.value)}
                        disabled={actorProfilesBusy}
                      >
                        <option value="">{actorProfilesBusy ? t("loadingProfiles") : t("selectActorProfile")}</option>
                        {actorProfiles.map((profile) => (
                          <option key={profile.id} value={profile.id}>
                            {profile.name || profile.id}
                          </option>
                        ))}
                      </select>
                    </div>

                    {selectedProfile ? (
                      <div className="rounded-xl border px-3 py-3 border-[var(--glass-border-subtle)] bg-[var(--glass-bg)] text-[var(--color-text-secondary)]">
                        <div className="text-sm font-medium text-[var(--color-text-primary)]">
                          {selectedProfile.name || selectedProfile.id}
                        </div>
                        <div className="mt-1 text-xs">
                          {RUNTIME_INFO[selectedProfileRuntime]?.label || selectedProfile.runtime}
                        </div>
                        {selectedProfileCommand ? (
                          <div className="mt-2 font-mono text-[11px] break-all text-[var(--color-text-tertiary)]">
                            {selectedProfileCommand}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <>
                    <div>
                      <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">{t("aiRuntime")}</label>
                      <select
                        className="w-full rounded-xl border px-4 py-2.5 text-sm min-h-[44px] transition-colors glass-input text-[var(--color-text-primary)]"
                        value={newActorRuntime}
                        onChange={(e) => {
                          const next = e.target.value as SupportedRuntime;
                          setNewActorRuntime(next);
                          setNewActorCommand("");
                          setNewActorUseDefaultCommand(next !== "custom");
                        }}
                      >
                        {SUPPORTED_RUNTIMES.map((rt) => {
                          const info = RUNTIME_INFO[rt];
                          const rtInfo = runtimes.find((r) => r.name === rt);
                          const available = rtInfo?.available ?? false;
                          const selectable = available || rt === "custom";
                          return (
                            <option key={rt} value={rt} disabled={!selectable}>
                              {info?.label || rt}
                              {!available && rt !== "custom" ? ` ${t("notInstalled")}` : ""}
                            </option>
                          );
                        })}
                      </select>
                      {RUNTIME_INFO[newActorRuntime]?.desc ? (
                        <div className="text-[10px] mt-1.5 text-[var(--color-text-muted)]">
                          {RUNTIME_INFO[newActorRuntime].desc}
                        </div>
                      ) : null}
                    </div>

                    {newActorRuntime !== "custom" ? (
                      <label className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                        <input
                          type="checkbox"
                          checked={newActorUseDefaultCommand}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setNewActorUseDefaultCommand(checked);
                            if (checked) setNewActorCommand("");
                          }}
                        />
                        {t("useRuntimeDefaultCommand")}
                      </label>
                    ) : null}

                    {/* Model Selection */}
                    {["claude", "gemini", "codex"].includes(newActorRuntime) && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="block text-xs font-medium text-[var(--color-text-muted)]">
                            {t("model", "Model")}
                          </label>
                          <button
                            type="button"
                            onClick={() => setShowAddCustomModel(!showAddCustomModel)}
                            className="text-xs text-blue-500 hover:underline"
                          >
                            {showAddCustomModel ? t("cancel", "Cancel") : t("addCustomModel", "Add Model")}
                          </button>
                        </div>

                        {/* Add Custom Model Form */}
                        {showAddCustomModel && (
                          <div className="mb-3 p-3 rounded-xl border border-[var(--glass-border-subtle)] bg-[var(--glass-bg)]">
                            <div className="flex gap-2">
                              <input
                                type="text"
                                value={customModelId}
                                onChange={(e) => setCustomModelId(e.target.value)}
                                placeholder={t("modelIdPlaceholder", "e.g., claude-sonnet-4-6")}
                                className="flex-1 rounded-lg border px-3 py-2 text-sm glass-input text-[var(--color-text-primary)]"
                              />
                              <button
                                type="button"
                                disabled={!customModelId.trim() || addingCustomModel}
                                onClick={async () => {
                                  if (!newActorRuntime || !customModelId.trim()) return;
                                  setAddingCustomModel(true);
                                  try {
                                    const resp = await api.addCustomModel({
                                      runtime: newActorRuntime,
                                      model_id: customModelId.trim(),
                                    });
                                    if (resp.ok) {
                                      const refreshResp = await api.fetchModelsByRuntime(newActorRuntime);
                                      const data = refreshResp as unknown as { ok: boolean; models?: ModelInfo[] };
                                      if (data.ok && data.models) {
                                        setModels(data.models);
                                      }
                                      setShowAddCustomModel(false);
                                      setCustomModelId("");
                                      if (resp.result?.model_key) {
                                        setNewActorModelId(resp.result.model_key);
                                      }
                                    }
                                  } finally {
                                    setAddingCustomModel(false);
                                  }
                                }}
                                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                              >
                                {addingCustomModel ? "..." : t("addModel", "Add")}
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Model List */}
                        {models.length > 0 ? (
                          <div className="rounded-xl border border-[var(--glass-border-subtle)] overflow-hidden">
                            {models.map((m) => (
                              <div
                                key={m.model_key}
                                className={`flex items-center gap-3 px-3 py-2.5 border-b border-[var(--glass-border-subtle)] last:border-b-0 cursor-pointer hover:bg-[var(--glass-tab-bg-hover)] ${
                                  m.enabled === false ? "opacity-50" : ""
                                } ${newActorModelId === m.model_key ? "bg-blue-500/10" : ""}`}
                                onClick={() => setNewActorModelId(newActorModelId === m.model_key ? "" : m.model_key)}
                              >
                                {/* Radio button */}
                                <input
                                  type="radio"
                                  name="model-select-add"
                                  checked={newActorModelId === m.model_key}
                                  onChange={() => {}}
                                  className="w-4 h-4 text-blue-600 pointer-events-none"
                                />
                                {/* Model name */}
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm text-[var(--color-text-primary)] truncate">
                                    {m.display_name || m.model_id}
                                  </div>
                                  {m.description && (
                                    <div className="text-xs text-[var(--color-text-muted)] truncate">
                                      {m.description}
                                    </div>
                                  )}
                                </div>
                                {/* Edit button */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingModelKey(m.model_key);
                                  }}
                                  title={t("editModelInfo", "Edit model info")}
                                  className="p-1.5 rounded hover:bg-[var(--glass-tab-bg)] transition-colors"
                                >
                                  <svg className="w-4 h-4 text-[var(--color-text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                  </svg>
                                </button>
                                {/* Visibility toggle */}
                                <button
                                  type="button"
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    await api.toggleModel(m.model_key, !m.enabled);
                                    if (newActorRuntime && newActorRuntime !== "custom") {
                                      const resp = await api.fetchModelsByRuntime(newActorRuntime);
                                      const data = resp as unknown as { ok: boolean; models?: ModelInfo[] };
                                      if (data.ok && data.models) {
                                        setModels(data.models);
                                      }
                                    }
                                  }}
                                  title={m.enabled !== false ? t("hideFromForeman", "Hide from Foreman") : t("showToForeman", "Show to Foreman")}
                                  className="p-1.5 rounded hover:bg-[var(--glass-tab-bg)] transition-colors"
                                >
                                  {m.enabled !== false ? (
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
                                {/* Delete button */}
                                <button
                                  type="button"
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    if (!confirm(t("deleteModelConfirm", "Delete this model?"))) return;
                                    await api.deleteCustomModel(m.model_key);
                                    if (newActorModelId === m.model_key) setNewActorModelId("");
                                    if (newActorRuntime && newActorRuntime !== "custom") {
                                      const resp = await api.fetchModelsByRuntime(newActorRuntime);
                                      const data = resp as unknown as { ok: boolean; models?: ModelInfo[] };
                                      if (data.ok && data.models) {
                                        setModels(data.models);
                                      }
                                    }
                                  }}
                                  title={t("deleteModel", "Delete model")}
                                  className="p-1.5 rounded hover:bg-red-500/10 transition-colors"
                                >
                                  <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                  </svg>
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-sm text-[var(--color-text-muted)] italic py-3">
                            {t("noModelsYet", "No models added yet. Click 'Add Model' to add one.")}
                          </div>
                        )}

                        {/* Model Edit Popup Modal */}
                        {editingModelKey && models.find((m) => m.model_key === editingModelKey) && (
                          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
                            <div className="bg-[var(--glass-panel-bg)] rounded-2xl border border-[var(--glass-border-subtle)] p-4 max-w-md w-full mx-4 shadow-xl">
                              <div className="flex items-center justify-between mb-3">
                                <h4 className="text-sm font-medium text-[var(--color-text-primary)]">
                                  {t("editModelInfo", "Edit model info")}
                                </h4>
                                <button
                                  type="button"
                                  onClick={() => setEditingModelKey(null)}
                                  className="p-1.5 rounded-lg hover:bg-[var(--glass-tab-bg)] transition-colors"
                                >
                                  <svg className="w-4 h-4 text-[var(--color-text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                  </svg>
                                </button>
                              </div>
                              <ModelInfoCard
                                model={models.find((m) => m.model_key === editingModelKey)!}
                                onUpdateDescription={async (description, bestFor) => {
                                  await api.updateModel(editingModelKey, { description, best_for: bestFor });
                                  if (newActorRuntime && newActorRuntime !== "custom") {
                                    const resp = await api.fetchModelsByRuntime(newActorRuntime);
                                    const data = resp as unknown as { ok: boolean; models?: ModelInfo[] };
                                    if (data.ok && data.models) {
                                      setModels(data.models);
                                    }
                                  }
                                }}
                                onRequestRating={async () => {
                                  if (!groupId) {
                                    alert(t("noGroupId", "No group selected"));
                                    return;
                                  }
                                  try {
                                    const resp = await api.requestModelReview(editingModelKey, groupId);
                                    if (resp.ok && resp.result) {
                                      if (resp.result.status === "sent") {
                                        alert(t("reviewRequestSent", "Evaluation request sent to Foreman"));
                                      }
                                      // Refresh models to show the new comment
                                      if (newActorRuntime && newActorRuntime !== "custom") {
                                        const modelResp = await api.fetchModelsByRuntime(newActorRuntime);
                                        const data = modelResp as unknown as { ok: boolean; models?: ModelInfo[] };
                                        if (data.ok && data.models) {
                                          setModels(data.models);
                                        }
                                      }
                                    } else {
                                      const errMsg = resp.ok ? "" : (resp.error?.message || t("reviewFailed", "No usage history yet"));
                                      alert(errMsg || t("reviewFailed", "No usage history yet"));
                                    }
                                  } catch {
                                    alert(t("reviewFailed", "No usage history yet"));
                                  }
                                }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {showCommandEditor ? (
                      <div>
                        <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">
                          {t("commandOverrideOptional")}
                        </label>
                        <input
                          className="w-full rounded-xl border px-4 py-2.5 text-sm font-mono min-h-[44px] transition-colors glass-input text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)]"
                          value={newActorCommand}
                          onChange={(e) => setNewActorCommand(e.target.value)}
                          placeholder={defaultCommand || t("enterCommand")}
                        />
                      </div>
                    ) : null}

                    {defaultCommand.trim() ? (
                      <div className="text-[10px] text-[var(--color-text-muted)]">
                        {newActorUseDefaultCommand && newActorRuntime !== "custom"
                          ? t("usingRuntimeDefaultCommand")
                          : t("default")}{" "}
                        <code className="px-1 rounded bg-[var(--glass-tab-bg)] text-[var(--color-text-secondary)]">
                          {displayCommand}
                        </code>
                      </div>
                    ) : null}

                    {newActorRuntime === "custom" || !runtimeAvailable ? (
                      <div className="rounded-xl border px-3 py-2 text-[11px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                        <div className="font-medium">{t("manualMcpRequired")}</div>
                        <div className="mt-1">{t("customCommandHint").replace(/<1>|<\/1>/g, "")}</div>
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            </section>

            {!newActorUseProfile ? (
              <details
                className={`group ${sectionCardClass}`}
                open={showAdvancedActor}
                onToggle={(e) => setShowAdvancedActor((e.currentTarget as HTMLDetailsElement).open)}
              >
                <summary className={collapsibleSummaryClass}>
                  <div>
                    <div className={sectionTitleClass}>{t("sectionAdvanced")}</div>
                    <div className={sectionHintClass}>{t("sectionAdvancedHint")}</div>
                  </div>
                  <span aria-hidden="true" className={collapsibleChevronClass}>
                    ⌄
                  </span>
                </summary>

                <div className="mt-4 space-y-4 border-t border-[var(--glass-border-subtle)] pt-4">
                  {showRuntimeSetup ? (
                    <details className={`group ${nestedCardClass}`}>
                      <summary className={collapsibleSummaryClass}>
                        <div>
                          <div className={collapsibleLabelClass}>{t("runtimeSetupSection")}</div>
                          <div className={sectionHintClass}>{t("runtimeSetupSectionHint")}</div>
                        </div>
                        <span aria-hidden="true" className={collapsibleChevronClass}>
                          ⌄
                        </span>
                      </summary>

                      <div className="mt-4 rounded-xl border px-3 py-2 text-[11px] border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                        <div className="font-medium">{t("manualMcpRequired")}</div>
                        {newActorRuntime === "custom" ? (
                          <>
                            <div className="mt-1">{t("customCommandHint").replace(/<1>|<\/1>/g, "")}</div>
                            <div className="mt-1">
                              {t("configureMcpStdio")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">cccc</code> {t("thatRuns")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">cccc mcp</code>.
                            </div>
                          </>
                        ) : newActorRuntime === "cursor" ? (
                          <>
                            <div className="mt-1">
                              {t("createEditFile")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">~/.cursor/mcp.json</code> (or{" "}
                              <code className="px-1 rounded bg-amber-500/15">.cursor/mcp.json</code> {t("orInProject")})
                            </div>
                            <div className="mt-1">{t("addMcpConfig")}</div>
                          </>
                        ) : newActorRuntime === "kilocode" ? (
                          <>
                            <div className="mt-1">
                              {t("createEditFile")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">.kilocode/mcp.json</code> {t("inProjectRoot")}
                            </div>
                            <div className="mt-1">{t("addMcpConfig")}</div>
                          </>
                        ) : newActorRuntime === "opencode" ? (
                          <>
                            <div className="mt-1">
                              {t("createEditFile")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">~/.config/opencode/opencode.json</code>
                            </div>
                            <div className="mt-1">{t("addMcpConfig")}</div>
                          </>
                        ) : (
                          <>
                            <div className="mt-1">
                              {t("createEditFile")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">~/.copilot/mcp-config.json</code>
                            </div>
                            <div className="mt-1">
                              {t("addMcpConfigOrFlag")}{" "}
                              <code className="px-1 rounded bg-amber-500/15">--additional-mcp-config</code>):
                            </div>
                          </>
                        )}

                        {newActorRuntime !== "custom" ? (
                          <pre className="mt-1.5 p-2 rounded overflow-x-auto whitespace-pre bg-amber-500/10 text-amber-800 dark:text-amber-200">
                            <code>
                              {newActorRuntime === "opencode"
                                ? OPENCODE_MCP_CONFIG_SNIPPET
                                : newActorRuntime === "copilot"
                                  ? COPILOT_MCP_CONFIG_SNIPPET
                                  : BASIC_MCP_CONFIG_SNIPPET}
                            </code>
                          </pre>
                        ) : null}

                        <div className="mt-1 text-[10px] text-amber-700/80 dark:text-amber-300/80">
                          {t("restartAfterConfig")}
                        </div>
                      </div>
                    </details>
                  ) : null}

                  <details className={`group ${nestedCardClass}`}>
                    <summary className={collapsibleSummaryClass}>
                      <div>
                        <div className={collapsibleLabelClass}>{t("capabilitiesSection")}</div>
                        <div className={sectionHintClass}>{t("capabilitiesSectionHint")}</div>
                      </div>
                      <span aria-hidden="true" className={collapsibleChevronClass}>
                        ⌄
                      </span>
                    </summary>

                    <div className="mt-4">
                      <CapabilityPicker
                        isDark={isDark}
                        value={parseCapabilityIdInput(newActorCapabilityAutoloadText)}
                        onChange={(next) => setNewActorCapabilityAutoloadText(formatCapabilityIdInput(next))}
                        disabled={busy === "actor-add"}
                        label={t("autoloadCapabilities")}
                        hint={t("autoloadCapabilitiesHint")}
                      />
                    </div>
                  </details>

                  <details className={`group ${nestedCardClass}`}>
                    <summary className={collapsibleSummaryClass}>
                      <div>
                        <div className={collapsibleLabelClass}>{t("secretsSection")}</div>
                        <div className={sectionHintClass}>{t("secretsSectionHint")}</div>
                      </div>
                      <span aria-hidden="true" className={collapsibleChevronClass}>
                        ⌄
                      </span>
                    </summary>

                    <div className="mt-4">
                      <label className="block text-xs font-medium mb-2 text-[var(--color-text-muted)]">
                        {t("secretsWriteOnly")}
                      </label>
                      <textarea
                        className="w-full rounded-xl border px-3 py-2 text-sm font-mono min-h-[112px] transition-colors glass-input text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)]"
                        value={newActorSecretsSetText}
                        onChange={(e) => setNewActorSecretsSetText(e.target.value)}
                        placeholder={'export OPENAI_API_KEY="...";\nexport ANTHROPIC_API_KEY="...";'}
                        spellCheck={false}
                      />
                      <div className="text-[10px] mt-1.5 text-[var(--color-text-muted)]">
                        {t("secretsStoredLocally").replace(/<1>|<\/1>/g, "")}
                      </div>
                      <div className="text-[10px] mt-1 text-[var(--color-text-muted)]">
                        {t("secretsFormat").replace(/<1>|<\/1>|<2>|<\/2>/g, "")}
                      </div>
                    </div>
                  </details>

                  <details className={`group ${nestedCardClass}`}>
                    <summary className={collapsibleSummaryClass}>
                      <div>
                        <div className={collapsibleLabelClass}>{t("profileToolsSection")}</div>
                        <div className={sectionHintClass}>{t("profileToolsSectionHint")}</div>
                      </div>
                      <span aria-hidden="true" className={collapsibleChevronClass}>
                        ⌄
                      </span>
                    </summary>

                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        type="button"
                        className="px-4 py-2.5 rounded-xl text-sm font-medium transition-colors min-h-[44px] border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-secondary)] hover:bg-[var(--glass-tab-bg-hover)]"
                        onClick={onSaveAsProfile}
                        disabled={busy === "actor-profile-save" || busy === "actor-add"}
                      >
                        {busy === "actor-profile-save" ? t("savingProfile") : t("addToActorProfiles")}
                      </button>
                    </div>
                  </details>
                </div>
              </details>
            ) : null}
          </div>
        </div>

        <div className="border-t px-4 py-3 sm:px-6 sm:py-4 safe-area-inset-bottom border-[var(--glass-border-subtle)] glass-header flex-shrink-0">
          {addActorError ? (
            <div
              className="mb-3 rounded-xl border px-3 py-2 text-xs border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300"
              role="alert"
            >
              <div className="flex items-start justify-between gap-3">
                <span>{addActorError}</span>
                <button
                  type="button"
                  className="text-rose-700 dark:text-rose-300 hover:opacity-80"
                  onClick={() => setAddActorError("")}
                  aria-label={t("common:close")}
                >
                  ×
                </button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-col-reverse sm:flex-row gap-3">
            <button
              type="button"
              className="px-4 py-2.5 rounded-xl text-sm font-medium transition-colors min-h-[44px] border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] text-[var(--color-text-secondary)] hover:bg-[var(--glass-tab-bg-hover)]"
              onClick={onCancelAndReset}
            >
              {t("common:cancel")}
            </button>

            <div className="flex-1 min-w-0">
              <button
                type="button"
                className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 text-white px-4 py-2.5 text-sm font-semibold shadow-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all min-h-[44px]"
                onClick={onAddActor}
                disabled={!canAddActor}
              >
                {busy === "actor-add" ? t("adding") : newActorUseProfile ? t("createFromProfile") : t("addAgent")}
              </button>
              {addActorDisabledReason ? (
                <div className="text-[10px] text-amber-600 dark:text-amber-300 mt-1.5">{addActorDisabledReason}</div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
