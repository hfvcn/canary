import React, { lazy, Suspense, useEffect, useMemo } from "react";
import { DropOverlay } from "./components/DropOverlay";
const AppModals = lazy(() => import("./components/AppModals").then((m) => ({ default: m.AppModals })));
import { AppBackground } from "./components/app/AppBackground";
import { AppFeedback } from "./components/app/AppFeedback";
import { AppShell } from "./components/app/AppShell";
import { useTheme } from "./hooks/useTheme";
import { useActorActions } from "./hooks/useActorActions";
import { useSSE } from "./hooks/useSSE";
import { useDragDrop } from "./hooks/useDragDrop";
import { useGroupActions } from "./hooks/useGroupActions";
import { useSwipeNavigation } from "./hooks/useSwipeNavigation";
import { useCrossGroupRecipients } from "./hooks/useCrossGroupRecipients";
import { useDeepLink } from "./hooks/useDeepLink";
import { useGlobalEvents } from "./hooks/useGlobalEvents";
import { useViewportHeight } from "./hooks/useViewportHeight";
import { useAppChrome } from "./hooks/useAppChrome";
import { useAppGroupLifecycle } from "./hooks/useAppGroupLifecycle";
import { useAppTabState } from "./hooks/useAppTabState";
import { WebPet } from "./features/webPet/WebPet";
import { getEffectiveComposerDestGroupId } from "./stores/useComposerStore";
import { getChatSession } from "./stores/useUIStore";
import {
  useGroupStore,
  useUIStore,
  useModalStore,
  useComposerStore,
  useFormStore,
  useWorkspaceStore,
} from "./stores";
import type { ChatMessageData, LedgerEvent } from "./types";

// ============ Main App Component ============

export default function App() {
  // Theme
  const { theme, setTheme, isDark } = useTheme();

  // Virtual keyboard viewport adjustment for mobile
  useViewportHeight();

  // Zustand stores
  const groups = useGroupStore((state) => state.groups);
  const groupOrder = useGroupStore((state) => state.groupOrder);
  const selectedGroupId = useGroupStore((state) => state.selectedGroupId);
  const groupDoc = useGroupStore((state) => state.groupDoc);
  const actors = useGroupStore((state) => state.actors);
  const groupContext = useGroupStore((state) => state.groupContext);
  const groupSettings = useGroupStore((state) => state.groupSettings);
  const setSelectedGroupId = useGroupStore((state) => state.setSelectedGroupId);
  const refreshGroups = useGroupStore((state) => state.refreshGroups);
  const refreshActors = useGroupStore((state) => state.refreshActors);
  const loadGroup = useGroupStore((state) => state.loadGroup);
  const warmGroup = useGroupStore((state) => state.warmGroup);
  const openChatWindow = useGroupStore((state) => state.openChatWindow);
  const closeChatWindow = useGroupStore((state) => state.closeChatWindow);
  const reorderGroups = useGroupStore((state) => state.reorderGroups);
  const getOrderedGroups = useGroupStore((state) => state.getOrderedGroups);

  const busy = useUIStore((s) => s.busy);
  const errorMsg = useUIStore((s) => s.errorMsg);
  const notice = useUIStore((s) => s.notice);
  const isTransitioning = useUIStore((s) => s.isTransitioning);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);
  const activeTab = useUIStore((s) => s.activeTab);
  const chatSessions = useUIStore((s) => s.chatSessions);
  const isSmallScreen = useUIStore((s) => s.isSmallScreen);
  const webReadOnly = useUIStore((s) => s.webReadOnly);
  const showError = useUIStore((s) => s.showError);
  const dismissError = useUIStore((s) => s.dismissError);
  const dismissNotice = useUIStore((s) => s.dismissNotice);
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed);
  const setSidebarWidth = useUIStore((s) => s.setSidebarWidth);
  const setActiveTab = useUIStore((s) => s.setActiveTab);
  const setShowScrollButton = useUIStore((s) => s.setShowScrollButton);
  const setChatUnreadCount = useUIStore((s) => s.setChatUnreadCount);
  const setSmallScreen = useUIStore((s) => s.setSmallScreen);
  const setWebReadOnly = useUIStore((s) => s.setWebReadOnly);
  const sseStatus = useUIStore((s) => s.sseStatus);

  const openModal = useModalStore((state) => state.openModal);
  const modalFlags = useModalStore((state) => state.modals);
  const editingActor = useModalStore((state) => state.editingActor);

  const {
    activeGroupId,
    destGroupId,
    composerFiles,
    replyTarget,
    setDestGroupId,
    setReplyTarget,
    setToText,
    switchGroup,
  } = useComposerStore();

  const { setNewActorRole, setEditGroupTitle, setEditGroupTopic, setDirSuggestions } = useFormStore();

  // Actor actions hook
  const {
    getTermEpoch,
    toggleActorEnabled,
    relaunchActor,
    editActor,
    removeActor,
    openActorInbox,
  } = useActorActions(selectedGroupId);

  const chatSession = useMemo(
    () => getChatSession(selectedGroupId, chatSessions),
    [selectedGroupId, chatSessions]
  );
  const chatUnreadCount = chatSession.chatUnreadCount;
  const chatSessionAtBottom = chatSession.scrollSnapshot?.atBottom;

  // Hide Panorama tab when browser lacks GPU/3D support or feature is disabled
  const canRender3D = useMemo(() => {
    try {
      const canvas = document.createElement("canvas");
      return !!(navigator.gpu || canvas.getContext("webgl2"));
    } catch { return false; }
  }, []);
  const showPanorama = canRender3D && !!groupSettings?.panorama_enabled;
  const [showMentionMenu, setShowMentionMenu] = React.useState(false);
  const [_mentionFilter, setMentionFilter] = React.useState("");
  const [mentionSelectedIndex, setMentionSelectedIndex] = React.useState(0);
  const [collapseHumanMessageBodiesByDefault] = React.useState(false);
  const ensureWorkspaceGroup = useWorkspaceStore((state) => state.ensureGroup);
  const refreshWorkspaceGroup = useWorkspaceStore((state) => state.refreshGroup);

  const {
    composerRef,
    fileInputRef,
    eventContainerRef,
    contentRef,
    activeTabRef,
    chatAtBottomRef,
    actorsRef,
    allTabs,
    renderedActorIds,
    resetMountedActorIds,
    handleTabChange,
  } = useAppTabState({
    activeTab,
    actors,
    selectedGroupId,
    chatSessionAtBottom,
    isSmallScreen,
    setActiveTab,
    setShowScrollButton,
    setChatUnreadCount,
  });

  // Custom hooks
  const { connectStream, fetchContext, cleanup: cleanupSSE, contextRefreshTimerRef } = useSSE({
    activeTabRef,
    chatAtBottomRef,
    actorsRef,
  });

  const { dropOverlayOpen, handleAppendComposerFiles, resetDragDrop, WEB_MAX_FILE_MB } = useDragDrop({
    selectedGroupId,
  });

  const { handleStartGroup, handleStopGroup, handleSetGroupState } = useGroupActions();

  const computedSendGroupId = getEffectiveComposerDestGroupId(destGroupId, activeGroupId, selectedGroupId);

  const { recipientActors, recipientActorsBusy, destGroupScopeLabel } = useCrossGroupRecipients({
    actors,
    groupDoc,
    selectedGroupId,
    composerGroupId: activeGroupId,
    sendGroupId: computedSendGroupId,
  });
  const sendGroupId = computedSendGroupId;

  const startReply = React.useCallback(
    (ev: LedgerEvent) => {
      if (!ev.id || ev.kind !== "chat.message") return;
      const data = ev.data as ChatMessageData | undefined;
      const text = data?.text ? String(data.text) : "";

      if (selectedGroupId) {
        setDestGroupId(selectedGroupId);
      }

      const by = String(ev.by || "").trim();
      const authorIsActor = by && by !== "user" && actors.some((a) => String(a.id || "") === by);
      const originalTo = Array.isArray(data?.to)
        ? data.to.map((token) => String(token || "").trim()).filter((token) => token)
        : [];
      const policy = groupSettings?.default_send_to || "foreman";
      const defaultTo = authorIsActor
        ? [by]
        : originalTo.length > 0
          ? originalTo
          : policy === "foreman"
            ? ["@foreman"]
            : [];
      setToText(defaultTo.join(", "));

      setReplyTarget({
        eventId: String(ev.id),
        by: String(ev.by || "unknown"),
        text: text.slice(0, 100) + (text.length > 100 ? "..." : ""),
      });
      requestAnimationFrame(() => composerRef.current?.focus());
    },
    [selectedGroupId, actors, composerRef, groupSettings, setDestGroupId, setReplyTarget, setToText]
  );

  const { parseUrlDeepLink } = useDeepLink({
    groups,
    selectedGroupId,
    setSelectedGroupId,
    setActiveTab,
    openChatWindow,
    showError,
  });

  useGlobalEvents({ refreshGroups });

  const { canManageGroups, ccccHome, fetchDirSuggestions } = useAppChrome({
    parseUrlDeepLink,
    refreshGroups,
    setWebReadOnly,
    setSmallScreen,
    showError,
    setDirSuggestions,
    groupEditOpen: modalFlags.groupEdit,
    addActorOpen: modalFlags.addActor,
    editingActor,
  });

  const { handleTouchStart, handleTouchEnd } = useSwipeNavigation({
    tabs: allTabs,
    activeTab,
    onTabChange: handleTabChange,
  });

  // Auto-fallback: switch away from panorama tab when feature is disabled
  useEffect(() => {
    if (!showPanorama && activeTab === "panorama") {
      setActiveTab("chat");
    }
  }, [showPanorama, activeTab, setActiveTab]);

  // BUG-1 + BUG-3: Refresh context on panorama tab activation + periodic polling fallback
  useEffect(() => {
    if (!showPanorama || activeTab !== "panorama" || !selectedGroupId) return;
    // Immediate fetch on tab switch (skip if SSE debounce timer is already pending)
    if (!contextRefreshTimerRef.current) {
      void fetchContext(selectedGroupId);
    }
    // 12s polling fallback while panorama tab is active
    const intervalId = window.setInterval(() => {
      void fetchContext(selectedGroupId);
    }, 12_000);
    return () => window.clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedGroupId]);

  const hasForeman = useMemo(() => actors.some((a) => a.role === "foreman"), [actors]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- groups and groupOrder trigger recalculation
  const orderedGroups = useMemo(() => getOrderedGroups(), [groups, groupOrder]);
  const selectedGroupMeta = useMemo(
    () => groups.find((g) => String(g.group_id || "") === selectedGroupId) || null,
    [groups, selectedGroupId]
  );
  const selectedGroupRunning = useMemo(() => {
    const anyActorRunning = actors.some((a) => !!a.running);
    return anyActorRunning || (selectedGroupMeta?.running ?? false);
  }, [actors, selectedGroupMeta]);

  const groupLabelById = useMemo(() => {
    const out: Record<string, string> = {};
    for (const g of groups || []) {
      const gid = String(g.group_id || "").trim();
      if (!gid) continue;
      const title = String(g.title || "").trim();
      out[gid] = title || gid;
    }
    return out;
  }, [groups]);

  const hasReplyTarget = !!replyTarget;
  const hasComposerFiles = composerFiles.length > 0;

  useAppGroupLifecycle({
    selectedGroupId,
    destGroupId,
    sendGroupId,
    hasReplyTarget,
    hasComposerFiles,
    setDestGroupId,
    switchGroup,
    fileInputRef,
    resetDragDrop,
    resetMountedActorIds,
    setActiveTab,
    closeChatWindow,
    loadGroup,
    connectStream,
    cleanupSSE,
  });

  // Ensure workspace group is loaded when switching groups
  useEffect(() => {
    if (!selectedGroupId) return;
    ensureWorkspaceGroup(selectedGroupId);
    void refreshWorkspaceGroup(selectedGroupId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroupId]);

  // ============ Actions ============

  return (
    <div
      className={`relative w-full overflow-hidden ${
        isDark ? "bg-black text-slate-100" : "bg-gradient-to-br from-slate-50 via-white to-slate-100"
      }`}
      style={{ height: "calc(100% - var(--vk-offset, 0px))" }}
    >
      <AppBackground isDark={isDark} />

      <AppShell
        orderedGroups={orderedGroups}
        groupOrder={groupOrder}
        groups={groups}
        selectedGroupId={selectedGroupId}
        groupDoc={groupDoc}
        groupContext={groupContext}
        actors={actors}
        recipientActors={recipientActors}
        recipientActorsBusy={recipientActorsBusy}
        destGroupScopeLabel={destGroupScopeLabel}
        renderedActorIds={renderedActorIds}
        activeTab={activeTab}
        busy={busy}
        isTransitioning={isTransitioning}
        sidebarOpen={sidebarOpen}
        sidebarCollapsed={sidebarCollapsed}
        sidebarWidth={sidebarWidth}
        isDark={isDark}
        isSmallScreen={isSmallScreen}
        webReadOnly={webReadOnly}
        selectedGroupRunning={selectedGroupRunning}
        theme={theme}
        sseStatus={sseStatus}
        groupLabelById={groupLabelById}
        chatUnreadCount={chatUnreadCount}
        mentionSelectedIndex={mentionSelectedIndex}
        showMentionMenu={showMentionMenu}
        composerRef={composerRef}
        fileInputRef={fileInputRef}
        eventContainerRef={eventContainerRef}
        contentRef={contentRef}
        chatAtBottomRef={chatAtBottomRef}
        onThemeChange={setTheme}
        onSelectGroup={setSelectedGroupId}
        onWarmGroup={(gid) => void warmGroup(gid)}
        onCreateGroup={
          !webReadOnly && canManageGroups
            ? () => {
                openModal("createGroup");
                void fetchDirSuggestions();
              }
            : undefined
        }
        onCloseSidebar={() => setSidebarOpen(false)}
        onToggleSidebar={toggleSidebarCollapsed}
        onResizeSidebar={setSidebarWidth}
        onReorderGroups={reorderGroups}
        onOpenSidebar={() => setSidebarOpen(true)}
        onOpenGroupEdit={
          canManageGroups
            ? () => {
                if (groupDoc) {
                  setEditGroupTitle(groupDoc.title || "");
                  setEditGroupTopic(groupDoc.topic || "");
                  openModal("groupEdit");
                }
              }
            : undefined
        }
        onOpenSearch={() => openModal("search")}
        onOpenContext={() => {
          if (selectedGroupId && !groupContext) void fetchContext(selectedGroupId);
          openModal("context");
        }}
        onStartGroup={handleStartGroup}
        onStopGroup={handleStopGroup}
        onSetGroupState={handleSetGroupState}
        onOpenSettings={() => openModal("settings")}
        onOpenMobileMenu={() => openModal("mobileMenu")}
        onTabChange={handleTabChange}
        onAddAgent={
          webReadOnly
            ? undefined
            : () => {
                setNewActorRole(hasForeman ? "peer" : "foreman");
                openModal("addActor");
              }
        }
        appendComposerFiles={handleAppendComposerFiles}
        setMentionFilter={setMentionFilter}
        setMentionSelectedIndex={setMentionSelectedIndex}
        setShowMentionMenu={setShowMentionMenu}
        getTermEpoch={getTermEpoch}
        onToggleActorEnabled={toggleActorEnabled}
        onRelaunchActor={relaunchActor}
        onEditActor={editActor}
        onRemoveActor={removeActor}
        onOpenActorInbox={openActorInbox}
        onRefreshActors={() => void refreshActors()}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      />

      <WebPet />

      <AppFeedback
        isDark={isDark}
        webReadOnly={webReadOnly}
        errorMsg={errorMsg}
        notice={notice}
        dismissError={dismissError}
        dismissNotice={dismissNotice}
      />

      <Suspense fallback={null}>
        <AppModals
          isDark={isDark}
          readOnly={webReadOnly}
          ccccHome={ccccHome}
          composerRef={composerRef}
          onStartReply={startReply}
          onThemeToggle={() => setTheme(isDark ? "light" : "dark")}
          onStartGroup={handleStartGroup}
          onStopGroup={handleStopGroup}
          onSetGroupState={handleSetGroupState}
          fetchContext={fetchContext}
          canManageGroups={canManageGroups}
          canAccessSettings={canManageGroups}
          collapseHumanMessageBodiesByDefault={collapseHumanMessageBodiesByDefault}
        />
      </Suspense>

      <WebPet />

      <DropOverlay isOpen={dropOverlayOpen} isDark={isDark} maxFileMb={WEB_MAX_FILE_MB} />
    </div>
  );
}
