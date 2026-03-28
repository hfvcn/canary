import type { ComponentType, CSSProperties } from "react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { ErrorBoundary } from "../ErrorBoundary";
import { TabBar } from "../TabBar";
import { AppHeader } from "../layout/AppHeader";
import { GroupSidebar } from "../layout/GroupSidebar";
import { ActorTab } from "../../pages/ActorTab";
import { ChatTab } from "../../pages/chat";
import type { Actor, GroupContext, GroupDoc, GroupMeta } from "../../types";
import { getWorkspaceGroupState, useWorkspaceStore } from "../../stores/useWorkspaceStore";
import { SIDEBAR_COLLAPSED_WIDTH, useUIStore } from "../../stores/useUIStore";

const LazyWorkflowTab = lazy(() => import("../../pages/WorkflowTab").then((m) => ({ default: m.WorkflowTab })));
const LazyBoardTab = lazy<ComponentType<{ isDark: boolean }>>(() =>
  import("./BoardTabContainer").then((m) => ({ default: m.BoardTabContainer }))
);
const LazyWorkspaceTab = lazy(() =>
  import("./WorkspaceTabContainer").then((m) => ({ default: m.WorkspaceTabContainer }))
);
const LazyPanoramaTab = lazy(() =>
  import("./PanoramaTabContainer").then((m) => ({ default: m.PanoramaTabContainer }))
);

type AppShellProps = {
  orderedGroups: GroupMeta[];
  groupOrder: string[];
  groups: GroupMeta[];
  selectedGroupId: string;
  groupDoc: GroupDoc | null;
  groupContext: GroupContext | null;
  actors: Actor[];
  recipientActors: Actor[];
  recipientActorsBusy: boolean;
  destGroupScopeLabel: string;
  renderedActorIds: string[];
  activeTab: string;
  busy: string;
  isTransitioning: boolean;
  sidebarOpen: boolean;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  isDark: boolean;
  isSmallScreen: boolean;
  webReadOnly: boolean;
  selectedGroupRunning: boolean;
  theme: "light" | "dark" | "system";
  sseStatus: "connected" | "connecting" | "disconnected";
  groupLabelById: Record<string, string>;
  chatUnreadCount: number;
  mentionSelectedIndex: number;
  showMentionMenu: boolean;
  composerRef: React.RefObject<HTMLTextAreaElement | null>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  eventContainerRef: React.MutableRefObject<HTMLDivElement | null>;
  contentRef: React.MutableRefObject<HTMLDivElement | null>;
  chatAtBottomRef: React.MutableRefObject<boolean>;
  onThemeChange: (theme: "light" | "dark" | "system") => void;
  onSelectGroup: (groupId: string) => void;
  onWarmGroup: (groupId: string) => void;
  onCreateGroup: (() => void) | undefined;
  onCloseSidebar: () => void;
  onToggleSidebar: () => void;
  onResizeSidebar: (width: number) => void;
  onReorderGroups: (fromIndex: number, toIndex: number) => void;
  onOpenSidebar: () => void;
  onOpenGroupEdit: (() => void) | undefined;
  onOpenSearch: () => void;
  onOpenContext: () => void;
  onStartGroup: () => void;
  onStopGroup: () => void;
  onSetGroupState: (state: "active" | "idle" | "paused") => void;
  onOpenSettings: () => void;
  onOpenMobileMenu: () => void;
  onTabChange: (tab: string) => void;
  onAddAgent: (() => void) | undefined;
  appendComposerFiles: (files: File[]) => void;
  setMentionFilter: React.Dispatch<React.SetStateAction<string>>;
  setMentionSelectedIndex: React.Dispatch<React.SetStateAction<number>>;
  setShowMentionMenu: React.Dispatch<React.SetStateAction<boolean>>;
  getTermEpoch: (actorId: string) => number;
  onToggleActorEnabled: (actor: Actor) => void;
  onRelaunchActor: (actor: Actor) => void;
  onEditActor: (actor: Actor) => void;
  onRemoveActor: (actor: Actor, activeTab: string) => void;
  onOpenActorInbox: (actor: Actor) => void;
  onRefreshActors: () => void;
  onTouchStart: (event: React.TouchEvent) => void;
  onTouchEnd: (event: React.TouchEvent) => void;
};

export function AppShell({
  orderedGroups,
  groupOrder,
  groups,
  selectedGroupId,
  groupDoc,
  groupContext,
  actors,
  recipientActors,
  recipientActorsBusy,
  destGroupScopeLabel,
  renderedActorIds,
  activeTab,
  busy,
  isTransitioning,
  sidebarOpen,
  sidebarCollapsed,
  sidebarWidth,
  isDark,
  isSmallScreen,
  webReadOnly,
  selectedGroupRunning,
  theme,
  sseStatus,
  groupLabelById,
  chatUnreadCount,
  mentionSelectedIndex,
  showMentionMenu,
  composerRef,
  fileInputRef,
  eventContainerRef,
  contentRef,
  chatAtBottomRef,
  onThemeChange,
  onSelectGroup,
  onWarmGroup,
  onCreateGroup,
  onCloseSidebar,
  onToggleSidebar,
  onResizeSidebar,
  onReorderGroups,
  onOpenSidebar,
  onOpenGroupEdit,
  onOpenSearch,
  onOpenContext,
  onStartGroup,
  onStopGroup,
  onSetGroupState,
  onOpenSettings,
  onOpenMobileMenu,
  onTabChange,
  onAddAgent,
  appendComposerFiles,
  setMentionFilter,
  setMentionSelectedIndex,
  setShowMentionMenu,
  getTermEpoch,
  onToggleActorEnabled,
  onRelaunchActor,
  onEditActor,
  onRemoveActor,
  onOpenActorInbox,
  onRefreshActors,
  onTouchStart,
  onTouchEnd,
}: AppShellProps) {
  const { t } = useTranslation("layout");
  const showError = useUIStore((state) => state.showError);
  const workspaceState = useWorkspaceStore((state) =>
    getWorkspaceGroupState(selectedGroupId, state.byGroup)
  );
  const refreshWorkspaceGroup = useWorkspaceStore((state) => state.refreshGroup);
  const openWorkspaceFolder = useWorkspaceStore((state) => state.openFolder);
  const openWorkspaceFile = useWorkspaceStore((state) => state.openFile);
  const createWorkspaceFolderAction = useWorkspaceStore((state) => state.createFolder);
  const createWorkspaceFileAction = useWorkspaceStore((state) => state.createFile);
  const shellStyle = {
    "--sidebar-width": `${sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth}px`,
  } as CSSProperties;

  async function handleOpenWorkspaceFile(path: string) {
    if (!selectedGroupId) return;
    await openWorkspaceFile(selectedGroupId, path);
    onTabChange("workspace");
  }

  async function handleOpenWorkspaceFolder(path: string) {
    if (!selectedGroupId) return;
    await openWorkspaceFolder(selectedGroupId, path);
  }

  async function handleCreateWorkspaceFolder(kind: "folder" | "task") {
    if (!selectedGroupId) return;
    const label = kind === "task" ? t("newTaskPrompt") : t("newFolderPrompt");
    const name = window.prompt(label, "");
    if (!name || !name.trim()) return;
    try {
      await createWorkspaceFolderAction(selectedGroupId, { name: name.trim(), kind });
    } catch (error) {
      showError(error instanceof Error ? error.message : t("workspaceCreateFailed"));
    }
  }

  async function handleCreateWorkspaceFile() {
    if (!selectedGroupId) return;
    const name = window.prompt(t("newFilePrompt"), "");
    if (!name || !name.trim()) return;
    try {
      await createWorkspaceFileAction(selectedGroupId, { name: name.trim() });
    } catch (error) {
      showError(error instanceof Error ? error.message : t("workspaceCreateFailed"));
    }
  }

  return (
    <div
      className="relative h-full transition-[grid-template-columns] duration-300 ease-out md:grid md:[grid-template-columns:var(--sidebar-width)_minmax(0,1fr)]"
      style={shellStyle}
    >
      <GroupSidebar
        orderedGroups={orderedGroups}
        groupOrder={groupOrder}
        selectedGroupId={selectedGroupId}
        isOpen={sidebarOpen}
        isCollapsed={sidebarCollapsed}
        sidebarWidth={sidebarWidth}
        isDark={isDark}
        readOnly={webReadOnly}
        onSelectGroup={onSelectGroup}
        onWarmGroup={onWarmGroup}
        onCreateGroup={onCreateGroup}
        onClose={onCloseSidebar}
        onToggleCollapse={onToggleSidebar}
        onResizeWidth={onResizeSidebar}
        onReorder={onReorderGroups}
        workspaceTree={workspaceState.tree}
        workspaceSelectedFilePath={workspaceState.openFilePath}
        workspaceLoading={workspaceState.loadingTree}
        workspaceError={workspaceState.error}
        onRefreshWorkspace={() => void refreshWorkspaceGroup(selectedGroupId)}
        onOpenWorkspaceFolder={handleOpenWorkspaceFolder}
        onOpenWorkspaceFile={handleOpenWorkspaceFile}
        onCreateWorkspaceFolder={handleCreateWorkspaceFolder}
        onCreateWorkspaceFile={handleCreateWorkspaceFile}
      />

      <main
        className={`absolute inset-0 flex h-full flex-col overflow-hidden md:relative md:inset-auto ${
          isDark ? "bg-black/75" : "bg-white/80"
        }`}
      >
        <AppHeader
          isDark={isDark}
          theme={theme}
          onThemeChange={onThemeChange}
          webReadOnly={webReadOnly}
          selectedGroupId={selectedGroupId}
          groupDoc={groupDoc}
          selectedGroupRunning={selectedGroupRunning}
          actors={actors}
          sseStatus={sseStatus}
          busy={busy}
          onOpenSidebar={onOpenSidebar}
          onOpenGroupEdit={onOpenGroupEdit}
          onOpenSearch={onOpenSearch}
          onOpenContext={onOpenContext}
          onStartGroup={onStartGroup}
          onStopGroup={onStopGroup}
          onSetGroupState={onSetGroupState}
          onOpenSettings={onOpenSettings}
          onOpenMobileMenu={onOpenMobileMenu}
        />

        {selectedGroupId ? (
          <TabBar
            actors={actors}
            activeTab={activeTab}
            onTabChange={onTabChange}
            unreadChatCount={chatUnreadCount}
            isDark={isDark}
            onAddAgent={onAddAgent}
            canAddAgent={!webReadOnly && !!selectedGroupId}
          />
        ) : null}

        <div
          ref={contentRef}
          className={`relative flex min-h-0 flex-1 flex-col overflow-hidden transition-opacity duration-150 ${
            isTransitioning ? "opacity-0" : "opacity-100"
          }`}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          <div
            className={`absolute inset-0 flex min-h-0 flex-col ${
              activeTab === "chat" ? "" : "invisible pointer-events-none"
            }`}
            aria-hidden={activeTab !== "chat"}
          >
            <ErrorBoundary>
              <ChatTab
                isDark={isDark}
                isSmallScreen={isSmallScreen}
                readOnly={webReadOnly}
                selectedGroupId={selectedGroupId}
                groupLabelById={groupLabelById}
                actors={actors}
                groups={groups}
                recipientActors={recipientActors}
                recipientActorsBusy={recipientActorsBusy}
                destGroupScopeLabel={destGroupScopeLabel}
                scrollRef={eventContainerRef}
                composerRef={composerRef}
                fileInputRef={fileInputRef}
                chatAtBottomRef={chatAtBottomRef}
                appendComposerFiles={appendComposerFiles}
                onStartGroup={onStartGroup}
                showMentionMenu={showMentionMenu}
                setShowMentionMenu={setShowMentionMenu}
                mentionSelectedIndex={mentionSelectedIndex}
                setMentionSelectedIndex={setMentionSelectedIndex}
                setMentionFilter={setMentionFilter}
              />
            </ErrorBoundary>
          </div>

          <div
            className={`absolute inset-0 flex min-h-0 flex-col ${
              activeTab === "chat" ? "invisible pointer-events-none" : ""
            }`}
            aria-hidden={activeTab === "chat"}
          >
            {renderedActorIds.map((actorId) => {
              const actor = actors.find((item) => item.id === actorId) || null;
              const isVisible = activeTab === actorId && activeTab !== "chat";
              const agentState =
                (groupContext?.agent_states || []).find((item) => item.id === (actor?.id || "")) || null;

              return (
                <div key={actorId} className={isVisible ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
                  <ErrorBoundary>
                    <ActorTab
                      actor={actor}
                      groupId={selectedGroupId}
                      agentState={agentState}
                      termEpoch={actor ? getTermEpoch(actor.id) : 0}
                      busy={busy}
                      isDark={isDark}
                      isSmallScreen={isSmallScreen}
                      isVisible={isVisible}
                      readOnly={webReadOnly}
                      onToggleEnabled={() => actor && onToggleActorEnabled(actor)}
                      onRelaunch={() => actor && onRelaunchActor(actor)}
                      onEdit={() => actor && onEditActor(actor)}
                      onRemove={() => actor && onRemoveActor(actor, activeTab)}
                      onInbox={() => actor && onOpenActorInbox(actor)}
                      onStatusChange={onRefreshActors}
                    />
                  </ErrorBoundary>
                </div>
              );
            })}

            {/* Workflow Tab */}
            <div className={activeTab === "workflow" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
              <ErrorBoundary>
                <Suspense fallback={null}>
                  <LazyWorkflowTab
                    groupId={selectedGroupId}
                    isDark={isDark}
                    onNavigateToActor={(actorId) => onTabChange(actorId)}
                  />
                </Suspense>
              </ErrorBoundary>
            </div>

            {/* Board Tab */}
            <div className={activeTab === "board" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
              <ErrorBoundary>
                <Suspense fallback={null}>
                  <LazyBoardTab isDark={isDark} />
                </Suspense>
              </ErrorBoundary>
            </div>

            {/* Workspace Tab */}
            <div className={activeTab === "workspace" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
              <ErrorBoundary>
                <Suspense fallback={null}>
                  <LazyWorkspaceTab />
                </Suspense>
              </ErrorBoundary>
            </div>

            {/* Panorama Tab */}
            <div className={activeTab === "panorama" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
              <ErrorBoundary>
                <Suspense fallback={null}>
                  <LazyPanoramaTab />
                </Suspense>
              </ErrorBoundary>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
