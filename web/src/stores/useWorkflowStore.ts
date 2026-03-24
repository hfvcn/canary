// Workflow state store (Ralph-Foreman workflow management).
import { create } from "zustand";
import * as api from "../services/api";

export interface WorkflowTask {
  id: string;
  title: string;
  type: "frontend" | "backend" | "general";
  status?: "pending" | "running" | "completed" | "failed";
  agent_name?: string;
  duration_seconds?: number;
  changed_files?: string[];
  error_message?: string;
}

export interface BatchSuggestion {
  suggestion_id: string;
  workflow_id: string;
  tasks: WorkflowTask[];
  rationale: string;
  estimated_parallelism: number;
  created_at: string;
}

export interface BatchDecision {
  decision_id: string;
  suggestion_id: string;
  workflow_id: string;
  decision: "approved" | "modified" | "rejected" | "deferred";
  approved_tasks: string[];
  rejected_tasks: string[];
  reason: string;
  created_at: string;
}

export interface WorkflowProgress {
  status: "idle" | "running";
  workflow_id?: string;
  current_batch?: string;
  batches?: { total: number; completed: number };
  tasks?: {
    total: number;
    completed: number;
    failed: number;
    running: number;
    pending: number;
  };
  duration?: {
    workflow_seconds: number;
    batch_seconds: number;
  };
  recent_events?: Array<{
    type: string;
    timestamp: number;
    [key: string]: unknown;
  }>;
}

interface WorkflowState {
  // Data
  pendingSuggestions: BatchSuggestion[];
  decisions: BatchDecision[];
  progress: WorkflowProgress | null;
  isLoading: boolean;
  error: string | null;

  // Selected workflow for detail view
  selectedWorkflowId: string;
  selectedSuggestionId: string;

  // Actions
  setPendingSuggestions: (suggestions: BatchSuggestion[]) => void;
  setDecisions: (decisions: BatchDecision[]) => void;
  setProgress: (progress: WorkflowProgress | null) => void;
  setIsLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setSelectedWorkflowId: (id: string) => void;
  setSelectedSuggestionId: (id: string) => void;

  // Async actions
  refreshPending: (workflowId?: string) => Promise<void>;
  refreshProgress: (groupId: string, workflowId?: string) => Promise<void>;
  submitBatch: (
    groupId: string,
    workflowId: string,
    tasks: WorkflowTask[],
    options?: {
      rationale?: string;
      autoProcess?: boolean;
      feishuChatId?: string;
    }
  ) => Promise<boolean>;
  processBatch: (
    groupId: string,
    suggestionId: string,
    options?: {
      feishuChatId?: string;
      autoStartAgents?: boolean;
    }
  ) => Promise<boolean>;
  clearWorkflow: (workflowId: string) => Promise<boolean>;
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  // Initial state
  pendingSuggestions: [],
  decisions: [],
  progress: null,
  isLoading: false,
  error: null,
  selectedWorkflowId: "",
  selectedSuggestionId: "",

  // Setters
  setPendingSuggestions: (suggestions) => set({ pendingSuggestions: suggestions }),
  setDecisions: (decisions) => set({ decisions }),
  setProgress: (progress) => set({ progress }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  setSelectedWorkflowId: (id) => set({ selectedWorkflowId: id }),
  setSelectedSuggestionId: (id) => set({ selectedSuggestionId: id }),

  // Async actions
  refreshPending: async (workflowId = "") => {
    set({ isLoading: true, error: null });
    try {
      const resp = await api.fetchWorkflowPending(workflowId, true);
      if (resp.ok && resp.result) {
        const result = resp.result as api.WorkflowPendingState;
        set({
          pendingSuggestions: result.pending_suggestions || [],
          decisions: result.decisions || [],
        });
      } else {
        set({ error: resp.error?.message || "Failed to fetch pending" });
      }
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ isLoading: false });
    }
  },

  refreshProgress: async (groupId, workflowId = "") => {
    try {
      const resp = await api.fetchWorkflowProgress(groupId, workflowId);
      if (resp.ok && resp.result) {
        set({ progress: resp.result as api.WorkflowProgress });
      }
    } catch (e) {
      console.warn("Failed to fetch workflow progress:", e);
    }
  },

  submitBatch: async (groupId, workflowId, tasks, options) => {
    set({ isLoading: true, error: null });
    try {
      const resp = await api.submitBatchSuggestion(groupId, workflowId, tasks, {
        rationale: options?.rationale,
        autoProcess: options?.autoProcess,
        feishuChatId: options?.feishuChatId,
      });
      if (resp.ok) {
        await get().refreshPending();
        return true;
      } else {
        set({ error: resp.error?.message || "Failed to submit batch" });
        return false;
      }
    } catch (e) {
      set({ error: String(e) });
      return false;
    } finally {
      set({ isLoading: false });
    }
  },

  processBatch: async (groupId, suggestionId, options) => {
    set({ isLoading: true, error: null });
    try {
      const resp = await api.processPendingBatch(groupId, suggestionId, options);
      if (resp.ok) {
        await get().refreshPending();
        await get().refreshProgress(groupId);
        return true;
      } else {
        set({ error: resp.error?.message || "Failed to process batch" });
        return false;
      }
    } catch (e) {
      set({ error: String(e) });
      return false;
    } finally {
      set({ isLoading: false });
    }
  },

  clearWorkflow: async (workflowId) => {
    try {
      const resp = await api.clearWorkflow(workflowId);
      if (resp.ok) {
        await get().refreshPending();
        set({ progress: null });
        return true;
      }
      return false;
    } catch {
      return false;
    }
  },
}));
