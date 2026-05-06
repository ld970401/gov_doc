/**
 * 会话集合 Store（options 写法，保证 actions 在运行时可调用，避免 setup store 在部分环境下方法丢失）。
 */
import { deleteConversation, listConversations, updateConversation } from '@/api';
import { defineStore } from 'pinia';

const LOCAL_SESSIONS_CACHE_KEY = 'chat_local_sessions_v1';

const readLocalSessions = (): ChatSession[] => {
  try {
    const raw = window.localStorage.getItem(LOCAL_SESSIONS_CACHE_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as ChatSession[];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
};

const writeLocalSessions = (list: ChatSession[]) => {
  try {
    window.localStorage.setItem(LOCAL_SESSIONS_CACHE_KEY, JSON.stringify(list));
  } catch {
    // ignore storage failures
  }
};

export const useSessionStore = defineStore('session', {
  state: () => ({
    sessions: [] as ChatSession[],
    loading: false,
    resetSignal: 0,
    scratchActiveSessionId: null as string | null,
  }),

  actions: {
    async loadHistory() {
      this.loading = true;
      try {
        const remoteList = (await listConversations()).map((item) => ({
          id: item.id,
          title: item.title,
          pinned: item.pinned,
          updatedAt: item.updatedAt,
          createdAt: item.updatedAt,
        })) as ChatSession[];
        const localOnly = readLocalSessions().filter(
          (localItem) => !remoteList.some((remoteItem) => remoteItem.id === localItem.id)
        );
        const list = [...localOnly, ...remoteList];
        list.sort((a, b) => {
          if (a.pinned && !b.pinned) return -1;
          if (!a.pinned && b.pinned) return 1;
          return 0;
        });
        this.sessions = list;
        writeLocalSessions(this.sessions);
      } catch {
        this.sessions = readLocalSessions();
      } finally {
        this.loading = false;
      }
    },

    findSession(id: string): ChatSession | undefined {
      return this.sessions.find((s) => s.id === id);
    },

    addSession(session: ChatSession) {
      if (!this.findSession(session.id)) {
        this.sessions.unshift(session);
        writeLocalSessions(this.sessions);
      }
    },

    setScratchActiveSession(id: string | null) {
      this.scratchActiveSessionId = id;
    },

    updateSessionTitleInList(conversationId: string, title: string) {
      const t = title.trim();
      if (!conversationId || !t) return;
      const item = this.findSession(conversationId);
      if (item) {
        item.title = t;
        writeLocalSessions(this.sessions);
      }
    },

    async renameSession(sessionId: string, title: string): Promise<void> {
      const item = this.findSession(sessionId);
      if (!item) return;
      try {
        await updateConversation(sessionId, { title });
      } catch {
        // local-only fallback session has no backend; keep local rename.
      }
      item.title = title;
      writeLocalSessions(this.sessions);
    },

    async togglePin(sessionId: string): Promise<boolean> {
      const item = this.findSession(sessionId);
      if (!item) return false;
      const next = !item.pinned;
      try {
        await updateConversation(sessionId, { pinned: next });
      } catch {
        // local-only fallback session has no backend; keep local pin state.
      }
      item.pinned = next;
      this.sessions.sort((a, b) => {
        if (a.pinned && !b.pinned) return -1;
        if (!a.pinned && b.pinned) return 1;
        return 0;
      });
      writeLocalSessions(this.sessions);
      return next;
    },

    async removeSession(sessionId: string): Promise<void> {
      try {
        await deleteConversation(sessionId);
      } catch {
        // local-only fallback session has no backend; remove locally anyway.
      }
      const idx = this.sessions.findIndex((s) => s.id === sessionId);
      if (idx > -1) this.sessions.splice(idx, 1);
      writeLocalSessions(this.sessions);
    },

    requestReset() {
      this.resetSignal += 1;
      this.scratchActiveSessionId = null;
    },
  },
});
