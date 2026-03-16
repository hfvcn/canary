import { create } from "zustand";
import type { WorkspaceEntry, WorkspaceFile, WorkspaceTree } from "../types";
import * as api from "../services/api";

type WorkspaceGroupState = {
  currentPath: string;
  tree: WorkspaceTree | null;
  tasks: WorkspaceEntry[];
  openFilePath: string;
  openFile: WorkspaceFile | null;
  loadingTree: boolean;
  loadingTasks: boolean;
  loadingFile: boolean;
  savingFile: boolean;
  uploadingFiles: boolean;
  error: string;
};

const EMPTY_WORKSPACE_GROUP_STATE: WorkspaceGroupState = {
  currentPath: "",
  tree: null,
  tasks: [],
  openFilePath: "",
  openFile: null,
  loadingTree: false,
  loadingTasks: false,
  loadingFile: false,
  savingFile: false,
  uploadingFiles: false,
  error: "",
};

function getBucket(byGroup: Record<string, WorkspaceGroupState>, groupId: string): WorkspaceGroupState {
  const gid = String(groupId || "").trim();
  return gid ? byGroup[gid] || EMPTY_WORKSPACE_GROUP_STATE : EMPTY_WORKSPACE_GROUP_STATE;
}

function patchBucket(
  byGroup: Record<string, WorkspaceGroupState>,
  groupId: string,
  patch: Partial<WorkspaceGroupState>
): Record<string, WorkspaceGroupState> {
  const gid = String(groupId || "").trim();
  if (!gid) return byGroup;
  return {
    ...byGroup,
    [gid]: {
      ...getBucket(byGroup, gid),
      ...patch,
    },
  };
}

interface WorkspaceState {
  byGroup: Record<string, WorkspaceGroupState>;
  ensureGroup: (groupId: string) => void;
  loadTree: (groupId: string, path?: string) => Promise<void>;
  loadTasks: (groupId: string) => Promise<void>;
  refreshGroup: (groupId: string) => Promise<void>;
  openFolder: (groupId: string, path: string) => Promise<void>;
  openFile: (groupId: string, path: string) => Promise<void>;
  clearOpenFile: (groupId: string) => void;
  createFolder: (groupId: string, args: { name: string; kind: "folder" | "task" }) => Promise<void>;
  createFile: (groupId: string, args: { name: string; content?: string }) => Promise<void>;
  saveFile: (groupId: string, args: { path: string; content: string }) => Promise<void>;
  uploadFiles: (groupId: string, files: File[]) => Promise<void>;
}

export function getWorkspaceGroupState(
  groupId: string | null | undefined,
  byGroup: Record<string, WorkspaceGroupState>
): WorkspaceGroupState {
  return getBucket(byGroup, String(groupId || "").trim());
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  byGroup: {},

  ensureGroup: (groupId) =>
    set((state) => ({
      byGroup: patchBucket(state.byGroup, groupId, {}),
    })),

  loadTree: async (groupId, path) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    const current = getBucket(get().byGroup, gid);
    const nextPath = path ?? current.currentPath;
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { loadingTree: true, error: "" }),
    }));
    const resp = await api.fetchWorkspaceTree(gid, nextPath);
    if (!resp.ok) {
      set((state) => ({
        byGroup: patchBucket(state.byGroup, gid, {
          loadingTree: false,
          error: `${resp.error.code}: ${resp.error.message}`,
        }),
      }));
      return;
    }
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, {
        tree: resp.result,
        currentPath: String(resp.result.rel_path || ""),
        loadingTree: false,
        error: "",
      }),
    }));
  },

  loadTasks: async (groupId) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { loadingTasks: true, error: "" }),
    }));
    const resp = await api.fetchWorkspaceTasks(gid);
    if (!resp.ok) {
      set((state) => ({
        byGroup: patchBucket(state.byGroup, gid, {
          loadingTasks: false,
          error: `${resp.error.code}: ${resp.error.message}`,
        }),
      }));
      return;
    }
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, {
        tasks: resp.result.items || [],
        loadingTasks: false,
        error: "",
      }),
    }));
  },

  refreshGroup: async (groupId) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    const current = getBucket(get().byGroup, gid);
    await Promise.all([
      get().loadTree(gid, current.currentPath),
      get().loadTasks(gid),
      current.openFilePath ? get().openFile(gid, current.openFilePath) : Promise.resolve(),
    ]);
  },

  openFolder: async (groupId, path) => {
    await get().loadTree(groupId, path);
  },

  openFile: async (groupId, path) => {
    const gid = String(groupId || "").trim();
    const filePath = String(path || "").trim();
    if (!gid || !filePath) return;
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { loadingFile: true, error: "" }),
    }));
    const resp = await api.fetchWorkspaceFile(gid, filePath);
    if (!resp.ok) {
      set((state) => ({
        byGroup: patchBucket(state.byGroup, gid, {
          loadingFile: false,
          error: `${resp.error.code}: ${resp.error.message}`,
        }),
      }));
      return;
    }
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, {
        openFile: resp.result,
        openFilePath: filePath,
        loadingFile: false,
        error: "",
      }),
    }));
  },

  clearOpenFile: (groupId) =>
    set((state) => ({
      byGroup: patchBucket(state.byGroup, groupId, { openFile: null, openFilePath: "" }),
    })),

  createFolder: async (groupId, args) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    const current = getBucket(get().byGroup, gid);
    const resp = await api.createWorkspaceFolder(gid, {
      parentPath: current.currentPath,
      name: args.name,
      kind: args.kind,
    });
    if (!resp.ok) {
      throw new Error(`${resp.error.code}: ${resp.error.message}`);
    }
    await Promise.all([get().loadTree(gid, current.currentPath), get().loadTasks(gid)]);
  },

  createFile: async (groupId, args) => {
    const gid = String(groupId || "").trim();
    if (!gid) return;
    const current = getBucket(get().byGroup, gid);
    const resp = await api.createWorkspaceFile(gid, {
      parentPath: current.currentPath,
      name: args.name,
      content: args.content || "",
    });
    if (!resp.ok) {
      throw new Error(`${resp.error.code}: ${resp.error.message}`);
    }
    await get().loadTree(gid, current.currentPath);
  },

  saveFile: async (groupId, args) => {
    const gid = String(groupId || "").trim();
    const filePath = String(args.path || "").trim();
    if (!gid || !filePath) return;
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { savingFile: true, error: "" }),
    }));
    const resp = await api.updateWorkspaceFile(gid, { path: filePath, content: args.content });
    if (!resp.ok) {
      set((state) => ({
        byGroup: patchBucket(state.byGroup, gid, {
          savingFile: false,
          error: `${resp.error.code}: ${resp.error.message}`,
        }),
      }));
      throw new Error(`${resp.error.code}: ${resp.error.message}`);
    }
    const current = getBucket(get().byGroup, gid);
    await Promise.all([get().loadTree(gid, current.currentPath), get().openFile(gid, filePath)]);
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { savingFile: false, error: "" }),
    }));
  },

  uploadFiles: async (groupId, files) => {
    const gid = String(groupId || "").trim();
    if (!gid || files.length === 0) return;
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { uploadingFiles: true, error: "" }),
    }));
    const current = getBucket(get().byGroup, gid);
    const resp = await api.uploadWorkspaceFiles(gid, { parentPath: current.currentPath, files });
    if (!resp.ok) {
      set((state) => ({
        byGroup: patchBucket(state.byGroup, gid, {
          uploadingFiles: false,
          error: `${resp.error.code}: ${resp.error.message}`,
        }),
      }));
      throw new Error(`${resp.error.code}: ${resp.error.message}`);
    }
    await get().loadTree(gid, current.currentPath);
    set((state) => ({
      byGroup: patchBucket(state.byGroup, gid, { uploadingFiles: false, error: "" }),
    }));
  },
}));
