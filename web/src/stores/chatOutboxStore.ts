// Chat Outbox Store — manages optimistic (pending) messages before server confirmation.
// Design: outbox entries are keyed by groupId, each entry has a localId for tracking.
// Selectors return stable references to avoid infinite re-render loops.

import { create } from "zustand";
import type { LedgerEvent } from "../types";

export type OutboxStatus = "pending" | "failed";

export interface OutboxEntry {
  localId: string;
  groupId: string;
  event: LedgerEvent; // The optimistic event shape for display
  status: OutboxStatus;
  createdAt: number;
}

interface ChatOutboxState {
  /** Outbox entries keyed by groupId. Each value is a stable array reference. */
  entriesByGroup: Record<string, OutboxEntry[]>;

  /** Add a pending message to the outbox. */
  enqueue: (groupId: string, localId: string, event: LedgerEvent) => void;

  /** Remove an entry by localId (on HTTP success or SSE reconciliation). */
  remove: (groupId: string, localId: string) => void;

  /** Mark an entry as failed (on HTTP error). */
  markFailed: (groupId: string, localId: string) => void;
}

export const useChatOutboxStore = create<ChatOutboxState>((set) => ({
  entriesByGroup: {},

  enqueue: (groupId, localId, event) =>
    set((state) => {
      const prev = state.entriesByGroup[groupId] || [];
      const entry: OutboxEntry = {
        localId,
        groupId,
        event,
        status: "pending",
        createdAt: Date.now(),
      };
      return {
        entriesByGroup: {
          ...state.entriesByGroup,
          [groupId]: [...prev, entry],
        },
      };
    }),

  remove: (groupId, localId) =>
    set((state) => {
      const prev = state.entriesByGroup[groupId];
      if (!prev || prev.length === 0) return state;
      const next = prev.filter((e) => e.localId !== localId);
      if (next.length === prev.length) return state; // no change
      return {
        entriesByGroup: {
          ...state.entriesByGroup,
          [groupId]: next,
        },
      };
    }),

  markFailed: (groupId, localId) =>
    set((state) => {
      const prev = state.entriesByGroup[groupId];
      if (!prev) return state;
      const idx = prev.findIndex((e) => e.localId === localId);
      if (idx === -1) return state;
      const next = prev.slice();
      next[idx] = { ...next[idx], status: "failed" };
      return {
        entriesByGroup: {
          ...state.entriesByGroup,
          [groupId]: next,
        },
      };
    }),
}));

/** Stable selector: returns the outbox entries array for a group (or empty array). */
const EMPTY: OutboxEntry[] = [];
export function selectOutboxEntries(state: ChatOutboxState, groupId: string): OutboxEntry[] {
  return state.entriesByGroup[groupId] || EMPTY;
}
