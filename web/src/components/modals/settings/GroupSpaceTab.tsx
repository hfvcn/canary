import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  GroupSpaceBinding,
  GroupSpaceProviderAuthStatus,
  GroupSpaceRemoteSpace,
  GroupSpaceStatus,
} from "../../../types";
import * as api from "../../../services/api";
import { cardClass, inputClass } from "./types";

interface GroupSpaceTabProps {
  isDark: boolean;
  groupId?: string;
  isActive?: boolean;
}

type NotebookLane = "work" | "memory";

const NOTEBOOK_LANES: NotebookLane[] = ["work", "memory"];

function normalizeNotebookSpaces(raw: unknown): GroupSpaceRemoteSpace[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item) => Boolean(String((item as GroupSpaceRemoteSpace | null)?.remote_space_id || "").trim()))
    .map((item) => ({
      remote_space_id: String((item as GroupSpaceRemoteSpace | null)?.remote_space_id || "").trim(),
      title: String((item as GroupSpaceRemoteSpace | null)?.title || "").trim(),
      created_at: String((item as GroupSpaceRemoteSpace | null)?.created_at || "").trim(),
      is_owner: Boolean((item as GroupSpaceRemoteSpace | null)?.is_owner),
    }));
}

function resolveDraftNotebookId(
  previousDraft: string,
  boundRemoteId: string,
  options: GroupSpaceRemoteSpace[]
): string {
  const bound = String(boundRemoteId || "").trim();
  if (bound) return bound;
  const previous = String(previousDraft || "").trim();
  if (previous && options.some((item) => String(item.remote_space_id || "").trim() === previous)) {
    return previous;
  }
  return String(options[0]?.remote_space_id || "").trim();
}

function mergeNotebookOptions(
  spaces: GroupSpaceRemoteSpace[],
  extraIds: Array<string | undefined>
): GroupSpaceRemoteSpace[] {
  const byId = new Map<string, GroupSpaceRemoteSpace>();
  for (const item of spaces) {
    const remoteId = String(item.remote_space_id || "").trim();
    if (!remoteId) continue;
    byId.set(remoteId, item);
  }
  for (const rawId of extraIds) {
    const remoteId = String(rawId || "").trim();
    if (!remoteId || byId.has(remoteId)) continue;
    byId.set(remoteId, { remote_space_id: remoteId, title: "", created_at: "", is_owner: false });
  }
  return Array.from(byId.values());
}

function bindingStateText(binding: GroupSpaceBinding | null | undefined, t: (key: string) => string): string {
  const status = String(binding?.status || "").trim();
  const remoteId = String(binding?.remote_space_id || "").trim();
  return status === "bound" && remoteId ? t("groupSpace.bound") : t("groupSpace.notBound");
}

export function GroupSpaceTab({ isDark: _isDark, groupId, isActive = true }: GroupSpaceTabProps) {
  const { t } = useTranslation("settings");
  const [provider] = useState("notebooklm");
  const [status, setStatus] = useState<GroupSpaceStatus | null>(null);
  const [authFlow, setAuthFlow] = useState<GroupSpaceProviderAuthStatus | null>(null);
  const [spaces, setSpaces] = useState<GroupSpaceRemoteSpace[]>([]);
  const [workBindRemoteId, setWorkBindRemoteId] = useState("");
  const [memoryBindRemoteId, setMemoryBindRemoteId] = useState("");
  const [loading, setLoading] = useState(false);
  const [spacesBusy, setSpacesBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [hint, setHint] = useState("");
  const [err, setErr] = useState("");
  const connectHintedFlowRef = useRef("");

  const providerState = status?.provider || null;
  const workBinding = status?.bindings?.work || null;
  const memoryBinding = status?.bindings?.memory || null;
  const workBoundRemoteId = String(workBinding?.remote_space_id || "").trim();
  const memoryBoundRemoteId = String(memoryBinding?.remote_space_id || "").trim();
  const authConfigured = Boolean(providerState?.auth_configured);
  const connectionState = String(authFlow?.state || "idle").trim() || "idle";
  const connectionRunning = connectionState === "running";
  const connectionConnected = authConfigured;
  const connectionWarning =
    String(authFlow?.error?.message || "").trim() || String(providerState?.last_error || "").trim();

  const notebookOptions = useMemo(
    () => mergeNotebookOptions(spaces, [workBoundRemoteId, memoryBoundRemoteId]),
    [spaces, workBoundRemoteId, memoryBoundRemoteId]
  );

  const workBoundNotebook = notebookOptions.find((item) => String(item.remote_space_id || "").trim() === workBoundRemoteId) || null;
  const memoryBoundNotebook = notebookOptions.find((item) => String(item.remote_space_id || "").trim() === memoryBoundRemoteId) || null;

  const connectionStatusText = useMemo(() => {
    if (connectionRunning) return t("groupSpace.accountConnecting");
    if (connectionConnected) return t("groupSpace.accountConnected");
    if (connectionState === "failed") return t("groupSpace.accountReconnectRequired");
    return t("groupSpace.accountNotConnected");
  }, [connectionConnected, connectionRunning, connectionState, t]);

  const connectionStatusTone = useMemo(() => {
    if (connectionRunning) return "text-sky-600 dark:text-sky-400";
    if (connectionConnected) return "text-emerald-600 dark:text-emerald-400";
    if (connectionState === "failed") return "text-amber-600 dark:text-amber-400";
    return "text-[var(--color-text-secondary)]";
  }, [connectionConnected, connectionRunning, connectionState]);

  const setHintWithTimeout = (text: string) => {
    setHint(text);
    window.setTimeout(() => setHint(""), 2400);
  };

  const loadAll = async () => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    setLoading(true);
    setErr("");
    try {
      let nextStatus: GroupSpaceStatus | null = null;
      let nextAuth: GroupSpaceProviderAuthStatus | null = null;
      let nextSpaces: GroupSpaceRemoteSpace[] = [];

      const statusResp = await api.fetchGroupSpaceStatus(gid, provider);
      if (!statusResp.ok) {
        setErr(statusResp.error?.message || t("groupSpace.loadFailed"));
      } else {
        nextStatus = statusResp.result || null;
        setStatus(nextStatus);
      }

      const authResp = await api.controlGroupSpaceProviderAuth({ provider, action: "status" });
      if (authResp.ok) {
        nextAuth = authResp.result?.auth || null;
        setAuthFlow(nextAuth);
      } else {
        setAuthFlow(null);
      }

      const shouldLoadSpaces = Boolean(nextStatus?.provider?.auth_configured);
      if (shouldLoadSpaces) {
        setSpacesBusy(true);
        try {
          const spacesResp = await api.fetchGroupSpaceSpaces(gid, provider);
          if (spacesResp.ok) {
            nextSpaces = normalizeNotebookSpaces(spacesResp.result?.spaces);
            setSpaces(nextSpaces);
          } else {
            setSpaces([]);
          }
        } finally {
          setSpacesBusy(false);
        }
      } else {
        setSpaces([]);
      }

      const nextWorkBoundRemoteId = String(nextStatus?.bindings?.work?.remote_space_id || "").trim();
      const nextMemoryBoundRemoteId = String(nextStatus?.bindings?.memory?.remote_space_id || "").trim();
      setWorkBindRemoteId((prev) => resolveDraftNotebookId(prev, nextWorkBoundRemoteId, nextSpaces));
      setMemoryBindRemoteId((prev) => resolveDraftNotebookId(prev, nextMemoryBoundRemoteId, nextSpaces));
    } catch (e) {
      setErr(e instanceof Error ? e.message : t("groupSpace.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isActive || !groupId) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh when active/group changes
  }, [isActive, groupId]);

  useEffect(() => {
    if (!isActive || !groupId || !connectionRunning) return;
    const pollOnce = async () => {
      try {
        const resp = await api.controlGroupSpaceProviderAuth({ provider, action: "status" });
        if (!resp.ok) {
          setErr(resp.error?.message || t("groupSpace.loadFailed"));
          return;
        }
        const nextAuth = resp.result?.auth || null;
        setAuthFlow(nextAuth);
        const nextState = String(nextAuth?.state || "").trim();
        if (nextState && nextState !== "running") {
          await loadAll();
          if (nextState === "succeeded") {
            const flowKey = String(nextAuth?.session_id || nextAuth?.started_at || "succeeded").trim();
            if (flowKey && connectHintedFlowRef.current !== flowKey) {
              connectHintedFlowRef.current = flowKey;
              setHintWithTimeout(t("groupSpace.googleConnectSuccess"));
            }
          }
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : t("groupSpace.loadFailed"));
      }
    };
    void pollOnce();
    const timer = window.setInterval(() => {
      void pollOnce();
    }, 3000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- poll only while auth flow is running
  }, [isActive, groupId, connectionRunning]);

  const handleConnectGoogle = async () => {
    setActionBusy(true);
    setErr("");
    try {
      const resp = await api.controlGroupSpaceProviderAuth({ provider, action: "start", timeoutSeconds: 900 });
      if (!resp.ok) {
        setErr(resp.error?.message || t("groupSpace.connectStartFailed"));
        return;
      }
      setAuthFlow(resp.result?.auth || null);
      setHintWithTimeout(t("groupSpace.connectStarted"));
    } catch {
      setErr(t("groupSpace.connectStartFailed"));
    } finally {
      setActionBusy(false);
    }
  };

  const handleCancelConnect = async () => {
    setActionBusy(true);
    setErr("");
    try {
      const resp = await api.controlGroupSpaceProviderAuth({ provider, action: "cancel" });
      if (!resp.ok) {
        setErr(resp.error?.message || t("groupSpace.connectCancelFailed"));
        return;
      }
      setAuthFlow(resp.result?.auth || null);
      setHintWithTimeout(t("groupSpace.connectCancelRequested"));
      await loadAll();
    } catch {
      setErr(t("groupSpace.connectCancelFailed"));
    } finally {
      setActionBusy(false);
    }
  };

  const handleBind = async (lane: NotebookLane, remoteSpaceId: string) => {
    const gid = String(groupId || "").trim();
    const rid = String(remoteSpaceId || "").trim();
    if (!gid || !rid) return;
    setActionBusy(true);
    setErr("");
    try {
      const resp = await api.bindGroupSpace(gid, rid, provider, lane);
      if (!resp.ok) {
        setErr(resp.error?.message || t("groupSpace.bindFailed"));
        return;
      }
      setStatus(resp.result || null);
      if (lane === "work") setWorkBindRemoteId(rid);
      else setMemoryBindRemoteId(rid);
      setHintWithTimeout(t("groupSpace.bindSuccess"));
      await loadAll();
    } catch {
      setErr(t("groupSpace.bindFailed"));
    } finally {
      setActionBusy(false);
    }
  };

  const handleCreateAndBind = async (lane: NotebookLane) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    setActionBusy(true);
    setErr("");
    try {
      const resp = await api.bindGroupSpace(gid, "", provider, lane);
      if (!resp.ok) {
        setErr(resp.error?.message || t("groupSpace.bindFailed"));
        return;
      }
      const nextRemoteId = String(resp.result?.bindings?.[lane]?.remote_space_id || "").trim();
      setStatus(resp.result || null);
      if (lane === "work") setWorkBindRemoteId(nextRemoteId);
      else setMemoryBindRemoteId(nextRemoteId);
      setHintWithTimeout(t("groupSpace.bindCreated"));
      await loadAll();
    } catch {
      setErr(t("groupSpace.bindFailed"));
    } finally {
      setActionBusy(false);
    }
  };

  const handleUnbind = async (lane: NotebookLane) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    const confirmText = t(lane === "work" ? "groupSpace.workUnbindConfirm" : "groupSpace.memoryUnbindConfirm");
    if (!window.confirm(confirmText)) return;
    setActionBusy(true);
    setErr("");
    try {
      const resp = await api.unbindGroupSpace(gid, provider, lane);
      if (!resp.ok) {
        setErr(resp.error?.message || t("groupSpace.unbindFailed"));
        return;
      }
      setStatus(resp.result || null);
      if (lane === "work") setWorkBindRemoteId("");
      else setMemoryBindRemoteId("");
      setHintWithTimeout(t("groupSpace.unbindSuccess"));
      await loadAll();
    } catch {
      setErr(t("groupSpace.unbindFailed"));
    } finally {
      setActionBusy(false);
    }
  };

  const renderNotebookCard = (lane: NotebookLane) => {
    const isWork = lane === "work";
    const binding = (isWork ? workBinding : memoryBinding) || null;
    const boundRemoteId = isWork ? workBoundRemoteId : memoryBoundRemoteId;
    const selectedRemoteId = isWork ? workBindRemoteId : memoryBindRemoteId;
    const setSelectedRemoteId = isWork ? setWorkBindRemoteId : setMemoryBindRemoteId;
    const boundNotebook = isWork ? workBoundNotebook : memoryBoundNotebook;
    const titleKey = isWork ? "groupSpace.workNotebookTitle" : "groupSpace.memoryNotebookTitle";
    const hintKey = isWork ? "groupSpace.workNotebookHint" : "groupSpace.memoryNotebookHint";
    const notebookStateText = bindingStateText(binding, t);
    const canManage = connectionConnected && !actionBusy;

    return (
      <div key={lane} className={cardClass()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-[var(--color-text-primary)]">{t(titleKey)}</div>
            <div className="mt-1 text-xs text-[var(--color-text-tertiary)]">{t(hintKey)}</div>
          </div>
          <div className="text-xs font-medium text-[var(--color-text-tertiary)]">{notebookStateText}</div>
        </div>

        <div className="mt-3 rounded-lg border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{t("groupSpace.currentNotebook")}</div>
          <div className="mt-1 text-sm font-medium break-all text-[var(--color-text-primary)]">
            {boundRemoteId
              ? (String(boundNotebook?.title || "").trim() || boundRemoteId)
              : t("groupSpace.notBound")}
          </div>
          {boundRemoteId ? (
            <div className="mt-1 text-[11px] font-mono break-all text-[var(--color-text-muted)]">{boundRemoteId}</div>
          ) : null}
        </div>

        <div className="mt-3">
          <label className="block text-[11px] mb-1 text-[var(--color-text-tertiary)]">{t("groupSpace.chooseNotebook")}</label>
          <select
            value={selectedRemoteId}
            onChange={(e) => setSelectedRemoteId(String(e.target.value || ""))}
            disabled={!connectionConnected || actionBusy || spacesBusy || !notebookOptions.length}
            className={inputClass()}
          >
            {!notebookOptions.length ? (
              <option value="">{t("groupSpace.noNotebookOptions")}</option>
            ) : null}
            {notebookOptions.map((item) => {
              const remoteId = String(item.remote_space_id || "").trim();
              const title = String(item.title || "").trim() || remoteId;
              return (
                <option key={remoteId} value={remoteId}>
                  {title}
                </option>
              );
            })}
          </select>
          {!connectionConnected ? (
            <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">{t("groupSpace.connectGoogleFirst")}</div>
          ) : connectionConnected && !notebookOptions.length ? (
            <div className="mt-1 text-[11px] text-[var(--color-text-tertiary)]">{t("groupSpace.noNotebookOptionsHint")}</div>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => void handleBind(lane, selectedRemoteId)}
            disabled={!canManage || !String(selectedRemoteId || "").trim()}
            className="px-3 py-2 rounded-lg text-sm min-h-[44px] font-medium transition-colors bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 disabled:opacity-50"
          >
            {t("groupSpace.bindSelected")}
          </button>
          <button
            onClick={() => void handleCreateAndBind(lane)}
            disabled={!canManage}
            className="glass-btn px-3 py-2 rounded-lg text-sm min-h-[44px] font-medium transition-colors text-[var(--color-text-primary)] disabled:opacity-50"
          >
            {t("groupSpace.createAndBind")}
          </button>
          <button
            onClick={() => void handleUnbind(lane)}
            disabled={!canManage || !boundRemoteId}
            className="px-3 py-2 rounded-lg text-sm min-h-[44px] font-medium transition-colors bg-rose-500/15 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 border border-rose-500/30 disabled:opacity-50"
          >
            {t("groupSpace.unbind")}
          </button>
        </div>
      </div>
    );
  };

  if (!groupId) {
    return <div className="text-sm text-[var(--color-text-tertiary)]">{t("groupSpace.openFromGroup")}</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">{t("groupSpace.title")}</h3>
          <p className="text-xs mt-1 max-w-3xl text-[var(--color-text-muted)]">{t("groupSpace.description")}</p>
        </div>
        <button
          onClick={() => void loadAll()}
          disabled={actionBusy || loading}
          className="glass-btn px-3 py-2 rounded-lg text-sm min-h-[44px] transition-colors text-[var(--color-text-primary)] disabled:opacity-50"
        >
          {loading ? t("common:loading") : t("groupSpace.refresh")}
        </button>
      </div>

      <div className={cardClass()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-[var(--color-text-primary)]">{t("groupSpace.accountTitle")}</div>
            <div className="mt-1 text-xs text-[var(--color-text-tertiary)]">{t("groupSpace.accountHint")}</div>
          </div>
          <div className={`text-xs font-medium ${connectionStatusTone}`}>{connectionStatusText}</div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => void handleConnectGoogle()}
            disabled={actionBusy || connectionRunning}
            className="px-3 py-2 rounded-lg text-sm min-h-[44px] font-medium transition-colors bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 disabled:opacity-50"
          >
            {connectionConnected ? t("groupSpace.reconnectGoogle") : t("groupSpace.connectGoogle")}
          </button>
          {connectionRunning ? (
            <button
              onClick={() => void handleCancelConnect()}
              disabled={actionBusy}
              className="px-3 py-2 rounded-lg text-sm min-h-[44px] font-medium transition-colors bg-rose-500/15 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 border border-rose-500/30 disabled:opacity-50"
            >
              {t("groupSpace.cancelConnect")}
            </button>
          ) : null}
        </div>

        {authFlow?.message ? (
          <div className="mt-3 text-xs text-[var(--color-text-tertiary)]">{String(authFlow.message)}</div>
        ) : null}
        {authFlow?.error?.message ? (
          <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">{String(authFlow.error.message)}</div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {NOTEBOOK_LANES.map((lane) => renderNotebookCard(lane))}
      </div>

      <div className={cardClass()}>
        <div className="text-sm font-semibold text-[var(--color-text-primary)]">{t("groupSpace.summaryTitle")}</div>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded-lg border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{t("groupSpace.summaryGoogle")}</div>
            <div className={`mt-1 text-sm font-medium ${connectionStatusTone}`}>{connectionStatusText}</div>
          </div>
          <div className="rounded-lg border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{t("groupSpace.summaryWork")}</div>
            <div className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">{bindingStateText(workBinding, t)}</div>
          </div>
          <div className="rounded-lg border border-[var(--glass-border-subtle)] bg-[var(--glass-panel-bg)] px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{t("groupSpace.summaryMemory")}</div>
            <div className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">{bindingStateText(memoryBinding, t)}</div>
          </div>
        </div>
        {connectionWarning ? (
          <div className="mt-3 text-xs text-amber-600 dark:text-amber-400">
            {t("groupSpace.summaryWarning")}: {connectionWarning}
          </div>
        ) : null}
      </div>

      {err ? <div className="text-xs text-rose-600 dark:text-rose-400">{err}</div> : null}
      {hint ? <div className="text-xs text-emerald-600 dark:text-emerald-400">{hint}</div> : null}
    </div>
  );
}
