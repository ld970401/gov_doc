<template>
  <div class="chat-shell" :class="{ 'editor-open': linkedEditorOpen && linkedEditorStep }">
    <main class="main-content">
      <div
        ref="scrollContainerRef"
        class="main-inner"
        @scroll="handleScroll"
        @wheel.passive="handleWheel"
      >
        <ConversationView
          v-if="conversationVisible"
          :messages="messages"
          :visible="conversationVisible"
          @copy="handleCopy"
          @thumb-up="handleThumbUp"
          @refresh="handleRefresh"
          @step-rendered="handleStepRendered"
          @steps-complete="handleStepsComplete"
        />
        <WelcomeSection v-else @question-click="handleQuestionClick" />
      </div>

      <DecisionActionBar
        v-if="activeDecision"
        :prompt="activeDecision.prompt"
        :description="activeDecision.description"
        :options="activeDecision.options"
        @action="handleDecisionAction"
        @close="closeDecisionBar"
      />
      <div v-show="!activeDecision" class="input-stack">
        <div v-if="showTaskProgressCard" class="task-progress-anchor">
          <TaskProgressCard :tasks="activeTaskProgressTasks" @close="handleCloseTaskProgressCard" />
        </div>
        <ChatInput ref="inputRef" @send="handleSend" @skill-select="handleSkillSelect" />
      </div>
    </main>

    <Transition name="linked-editor">
      <div
        v-if="linkedEditorOpen && linkedEditorStep"
        class="linked-editor-shell"
        :key="linkedPanelKey"
      >
        <aside class="linked-editor-aside">
          <LinkedEditorPanel :step="linkedEditorStep" @close="closeLinkedEditor" />
        </aside>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
/**
 * /chat 路由视图。
 *
 * 该视图只负责"右侧主内容"：会话流、输入框、任务进度、链接编辑器。
 * Sidebar 与 CloudDisk 已迁出到 MainLayout 与 /workspace 路由。
 *
 * ── 会话身份策略 ─────────────────────────────────────────────
 *   - URL = /chat（无 sessionId）：欢迎页或"临时会话(scratch)"。
 *     首次发问会向后端 runNewConversation 创建真实会话，但 URL 仍保持 /chat，
 *     仅把新会话登记到 Sidebar 列表。当前 scratch 的真实 id 缓存在 activeRealSessionId。
 *   - URL = /chat/:sessionId：从后端拉取该会话详情（历史会话或用户从 Sidebar 主动跳入）。
 *
 *   离开 /chat（切到 /workspace 或点击别的会话）后，scratch 状态在 ChatView 卸载/重置时丢失，
 *   想要回到刚才的对话只能通过 Sidebar 点击对应历史项 → /chat/:sessionId 触发后端回拉。
 *
 * ── 路由 / 重置信号 ─────────────────────────────────────────
 *   "新对话"按钮不再创建本地草稿，而是 router.push('/chat') + sessionStore.requestReset()，
 *   后者通过 watch(resetSignal) 通知本视图清空 activeRealSessionId / messages / SSE。
 */
import { getConversationDetail, runConversation, runNewConversation } from '@/api';
import { createSSEConnection, type StreamEvent } from '@/api/chat';
import { useSessionStore } from '@/stores/session';
import { LINKED_EDITOR_KEY } from '@/views/chat/linkedEditor';
import { computed, nextTick, onUnmounted, provide, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import ChatInput from './components/ChatInput.vue';
import ConversationView from './components/ConversationView.vue';
import DecisionActionBar from './components/DecisionActionBar.vue';
import LinkedEditorPanel from './components/LinkedEditorPanel.vue';
import TaskProgressCard, { type TaskItem } from './components/TaskProgressCard.vue';
import WelcomeSection from './components/WelcomeSection.vue';
import { mapBackendMessages } from './messageModel';
import { createSseStepReducer } from './sseStepReducer';
import { useChatScrollController } from './useChatScrollController';

const LOCAL_HISTORY_CACHE_KEY = 'chat_local_history_v1';

interface SendData {
  text: string;
  model?: string;
  claw?: string | null;
  skill?: string | null;
  skillLabel?: string | null;
}

interface AssistantMessageData {
  text?: string;
  textVisible?: boolean;
  steps?: Step[];
  decisionPrompt?: ChatMessage['decisionPrompt'];
  streaming?: boolean;
}

const route = useRoute();
const sessionStore = useSessionStore();

const readLocalHistoryCache = (): Record<string, ChatMessage[]> => {
  try {
    const raw = window.localStorage.getItem(LOCAL_HISTORY_CACHE_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw) as Record<string, ChatMessage[]>;
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
};

const writeLocalHistoryCache = (cache: Record<string, ChatMessage[]>) => {
  try {
    window.localStorage.setItem(LOCAL_HISTORY_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // ignore storage failures
  }
};

/**
 * URL 中带的会话 id。空字符串表示当前在 /chat（欢迎页 / scratch）。
 * 仅作为 loadSessionFromRoute 的输入；scratch 期间不会被改写。
 */
const currentSessionId = computed(() => {
  const raw = route.params.sessionId;
  return typeof raw === 'string' && raw ? raw : '';
});

/**
 * 当前 /chat scratch 关联的真实 conversationId。
 *   - 用户首次发送、SSE 拿到 conversationId 后写入；
 *   - 后续在同一 /chat 上发送时，作为续写的 conversationId 给 runConversation；
 *   - 用户点击 Sidebar 上"该 scratch 对应的历史项"时，URL 变成 /chat/:id，
 *     loadSessionFromRoute 会识别 sessionId === activeRealSessionId 直接复用内存状态；
 *   - 离开 /chat 或点"新对话"重置时清掉。
 */
const activeRealSessionId = ref<string | null>(null);

// ---------- 链接编辑器（右侧抽屉）----------
const linkedEditorOpen = ref(false);
const linkedEditorStep = ref<Step | null>(null);
const linkedPanelKey = computed(() => {
  const s = linkedEditorStep.value;
  if (!s) return 'none';
  return (s as { clientStepId?: string }).clientStepId || s.label || 'doc';
});

const openLinkedEditor = (step: Step) => {
  linkedEditorStep.value = step;
  linkedEditorOpen.value = true;
};

const closeLinkedEditor = () => {
  linkedEditorOpen.value = false;
  linkedEditorStep.value = null;
};

provide(LINKED_EDITOR_KEY, {
  open: openLinkedEditor,
  close: closeLinkedEditor,
  activeStep: linkedEditorStep,
  isOpen: linkedEditorOpen,
});

// ---------- 主消息流 ----------
const conversationVisible = ref(false);
/** 页面级唯一消息源：子组件只消费，不二次维护镜像状态。 */
const messages = ref<ChatMessage[]>([]);
const activeDecision = ref<ChatMessage['decisionPrompt'] | null>(null);

const activeTaskProgressTasks = computed<TaskItem[]>(() => {
  const latestAssistant = [...messages.value].reverse().find((msg) => msg.role === 'assistant');
  if (!latestAssistant) return [];
  const steps = latestAssistant.steps || [];
  for (let i = steps.length - 1; i >= 0; i--) {
    const step = steps[i];
    if (!step.content || typeof step.content !== 'object') continue;
    const tasks = (step.content as { tasks?: TaskItem[] }).tasks;
    if (Array.isArray(tasks) && tasks.length) return tasks;
  }
  return [];
});

const taskProgressDismissed = ref(false);
const showTaskProgressCard = computed(
  () =>
    !activeDecision.value &&
    activeTaskProgressTasks.value.length > 0 &&
    !taskProgressDismissed.value
);

const {
  scrollContainerRef,
  autoScroll,
  isRestoringHistory,
  isSwitchingSession,
  canAutoScroll,
  scrollToBottom,
  handleScroll,
  handleWheel,
} = useChatScrollController();
const forceScrollBottom = () => scrollToBottom('auto', true);
const forceLayoutContentToBottom = () => {
  const run = () => {
    const container = scrollContainerRef.value;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  };
  run();
  nextTick(() => {
    run();
    requestAnimationFrame(() => {
      run();
      setTimeout(run, 50);
      setTimeout(run, 120);
    });
  });
};

watch(
  () => messages.value.length,
  (len) => {
    if (len === 0) {
      activeDecision.value = null;
      return;
    }
    if (canAutoScroll()) scrollToBottom('smooth');
  }
);

watch(
  () => {
    return messages.value[messages.value.length - 1]?.steps?.length || 0;
  },
  () => {
    if (canAutoScroll()) scrollToBottom('smooth');
  }
);

watch(
  () => conversationVisible.value,
  (newVal) => {
    if (!newVal) return;
    // 从详情恢复会话时不要打开「跟到底」；否则后续子组件事件仍会触发滚到底。
    if (isRestoringHistory.value || isSwitchingSession.value) return;
    autoScroll.value = true;
    if (canAutoScroll()) scrollToBottom('smooth');
  }
);

const inputRef = ref<InstanceType<typeof ChatInput> | null>(null);
const activeStream = ref<{ close: () => void } | null>(null);
const getActiveConversationId = () => currentSessionId.value || activeRealSessionId.value || '';

const handleQuestionClick = (question: string) => {
  if (inputRef.value) inputRef.value.setInputText(question);
};

// ---------- URL / 重置信号 驱动的会话切换 ----------

/** 关闭并清理与当前会话相关的所有运行时状态。 */
const resetRuntimeState = () => {
  activeStream.value?.close();
  activeStream.value = null;
  activeDecision.value = null;
  taskProgressDismissed.value = false;
  autoScroll.value = true;
};

/** 根据当前 URL 加载对应会话的 messages。 */
const loadSessionFromRoute = async () => {
  const sessionId = currentSessionId.value;

  // 特例：URL 切到的正是当前 scratch 关联的真实会话 ——
  // 内存中的 messages / SSE 都是有效的，仅做"URL 同步"，不重新拉详情、不打断流式。
  if (sessionId && sessionId === activeRealSessionId.value && messages.value.length > 0) {
    // URL 已带上 id，高亮以路由为准，避免与 scratch 标记双轨。
    sessionStore.setScratchActiveSession(null);
    return;
  }

  // 离开 scratch（包括 sessionId 为空或切到另一个会话），先清空运行时状态。
  resetRuntimeState();
  activeRealSessionId.value = null;
  sessionStore.setScratchActiveSession(null);

  if (!sessionId) {
    // /chat 不带 sessionId：欢迎页。
    messages.value = [];
    conversationVisible.value = false;
    return;
  }

  isRestoringHistory.value = true;
  isSwitchingSession.value = true;
  try {
    const detail = await getConversationDetail(sessionId);
    messages.value = mapBackendMessages(detail.messages);
    conversationVisible.value = messages.value.length > 0;
  } catch (error) {
    const localHistory = readLocalHistoryCache()[sessionId];
    if (Array.isArray(localHistory) && localHistory.length > 0) {
      messages.value = localHistory;
      conversationVisible.value = true;
    } else {
      console.error('加载会话详情失败:', error);
      messages.value = [];
      conversationVisible.value = false;
    }
  } finally {
    // 若在 finally 里同步清掉标记，本轮响应式更新触发的 watch 会看到「已非切换态」，
    // canAutoScroll 为真并滚到底。延后到下一帧再清，切换会话时保持当前滚动位置。
    nextTick(() => {
      nextTick(() => {
        isRestoringHistory.value = false;
        isSwitchingSession.value = false;
        autoScroll.value = false;
      });
    });
  }
};

watch(currentSessionId, () => void loadSessionFromRoute(), { immediate: true });

/**
 * 监听"新对话"按钮发出的重置信号。
 * 即使 URL 已经在 /chat 不会触发上面的 watch，也能在这里把 scratch 状态彻底清掉。
 */
watch(
  () => sessionStore.resetSignal,
  () => {
    resetRuntimeState();
    activeRealSessionId.value = null;
    messages.value = [];
    conversationVisible.value = false;
  }
);

// ---------- 用户操作处理 ----------

const handleSend = async (data: SendData) => {
  if (!data.text.trim()) return;
  activeDecision.value = null;
  // 每轮新提问都销毁上一轮任务卡，直到本轮规划步骤重新产出 tasks。
  taskProgressDismissed.value = false;
  autoScroll.value = true;
  conversationVisible.value = true;
  addUserMessage(data.text, null, data.skillLabel || data.skill || data.claw || null);
  forceLayoutContentToBottom();
  forceScrollBottom();
  processAssistantResponse(data);
};

const handleDecisionAction = (option: {
  id: string;
  label: string;
  sendText?: string;
  text?: string;
}) => {
  activeDecision.value = null;
  if (option.sendText) {
    handleSend({ text: option.sendText, model: 'Qwen 3.5', claw: null });
    return;
  }
  inputRef.value?.setInputText(option.text || '');
};

const closeDecisionBar = () => {
  activeDecision.value = null;
};

const handleCloseTaskProgressCard = () => {
  taskProgressDismissed.value = true;
};

const handleSkillSelect = (claw: string | null) => {
  console.log('选择 Claw:', claw);
};

const handleCopy = (message: ChatMessage) => {
  console.log('复制消息:', message);
};

const handleThumbUp = (message: ChatMessage) => {
  console.log('点赞:', message);
};

const handleRefresh = (message: ChatMessage) => {
  console.log('重新生成:', message);
};

const handleStepRendered = (_payload: {
  messageId: string;
  stepKey: string;
  phase: 'revealed';
}) => {
  if (autoScroll.value && !isSwitchingSession.value) scrollToBottom();
};

const handleStepsComplete = (payload: { messageId: string; phase: 'all_completed' }) => {
  // 注意："步骤都已渲染"不等于"SSE 已结束"。
  // 真实结束只应由 message_stop / onDone / onError 驱动，
  // 否则会在检索完成到写作开始的等待期提前关闭 streaming，
  // 导致 AgentSteps 的"正在思考中"提示消失。
  void payload;
};

const addUserMessage = (content: string, attachment: any = null, skill: string | null = null) => {
  const message: ChatMessage = {
    id: `user-${Date.now()}`,
    role: 'user',
    content,
    attachment,
    skill,
    createdAt: new Date().toISOString(),
  };
  messages.value.push(message);
  // 注：scratch 与真实会话的用户消息均由后端在 runConversation/runNewConversation 时持久化，
  // 前端仅 push 到内存用于即时渲染，不再做本地落盘。
};

const addAssistantMessage = (data: AssistantMessageData) => {
  const message: ChatMessage = {
    id: `assistant-${Date.now()}`,
    role: 'assistant',
    content: '',
    createdAt: new Date().toISOString(),
    ...data,
  };
  messages.value.push(message);
};

const processAssistantResponse = (data: SendData) => {
  // 创建一条空的 assistant 消息作为 SSE 落点。
  const assistantMessageIndex = messages.value.length;
  addAssistantMessage({
    steps: [],
    text: '',
    textVisible: false,
    streaming: true,
  });

  // 决定走哪个 endpoint：
  //   - URL 上有 sessionId（用户从历史会话进来）→ 用 URL 上的 id；
  //   - 否则若 scratch 已经有真实 id（同一 /chat 上的非首条消息）→ 用 scratch id；
  //   - 都没有则视为首次发问，走 runNewConversation。
  const targetId = currentSessionId.value || activeRealSessionId.value;

  const payload = {
    content: data.text,
    model: data.model,
    skill: data.skill || data.claw || null,
  };

  /**
   * 运行会话并建立 SSE 连接。
   * 首次发送（没有 targetId）时拿到真实 conversationId 后：
   *   - 写入 activeRealSessionId 让后续消息走续写；
   *   - 把会话登记到 Sidebar 历史列表；
   *   - **不**修改 URL，让 /chat 在用户离开前一直保持纯净。
   */
  const connect = async () => {
    try {
      const runRes = targetId
        ? await runConversation(targetId, payload)
        : await runNewConversation(payload);

      const titleFromRun = runRes.conversationTitle?.trim() || '';
      if (titleFromRun) {
        sessionStore.updateSessionTitleInList(runRes.conversationId, titleFromRun);
      }

      if (!targetId) {
        activeRealSessionId.value = runRes.conversationId;
        const ts = new Date().toISOString();
        const listTitle =
          titleFromRun || data.text.trim().slice(0, 20) || '新对话';
        sessionStore.addSession({
          id: runRes.conversationId,
          title: listTitle,
          pinned: false,
          createdAt: ts,
          updatedAt: ts,
        });
        if (!currentSessionId.value) {
          sessionStore.setScratchActiveSession(runRes.conversationId);
        }
      }

      // 每条 assistant 消息绑定一个 reducer，保证同一轮事件只修改本消息 steps。
      const currentMsg = messages.value[assistantMessageIndex];
      const stepList = currentMsg?.steps || [];
      const reducer = createSseStepReducer(stepList);

      activeStream.value?.close();
      activeStream.value = createSSEConnection(runRes.streamUrl, {
        onEvent: (event: StreamEvent) => {
          if (event.type === 'message_stop') {
            reducer.apply(event);
            const message = messages.value[assistantMessageIndex];
            if (message) message.streaming = false;
            forceScrollBottom();
            return;
          }
          reducer.apply(event);
          forceScrollBottom();
        },
        onDone: () => {
          // 流结束时只做两件事：
          //   1. 兜底把任务卡里残留的 in_progress 任务置 completed（reducer 内部处理）；
          //   2. 关闭消息的 streaming 标记。
          // 不再回拉 getConversationDetail —— 文档正文已由 documentOutput step 渲染。
          const currentMsg = messages.value[assistantMessageIndex];
          if (!currentMsg) return;
          reducer.apply({ type: 'message_stop' });
          currentMsg.streaming = false;
          forceScrollBottom();
        },
        onError: (error: Error) => {
          console.error('Stream connection error:', error);
          const currentMsg = messages.value[assistantMessageIndex];
          if (currentMsg) {
            currentMsg.streaming = false;
            currentMsg.text = '抱歉，连接中断，请重试。';
            currentMsg.textVisible = true;
          }
          forceScrollBottom();
        },
      });
    } catch (error) {
      const currentMsg = messages.value[assistantMessageIndex];
      if (currentMsg) {
        currentMsg.streaming = false;
        currentMsg.text = '抱歉，请求失败，请稍后重试。';
        currentMsg.textVisible = true;
      }
      console.error('运行会话失败:', error);
    }
  };

  void connect();
};

onUnmounted(() => {
  activeStream.value?.close();
  activeStream.value = null;
  sessionStore.setScratchActiveSession(null);
});

watch(
  () => [messages.value, getActiveConversationId()] as const,
  ([list, sessionId]) => {
    if (!sessionId || !Array.isArray(list)) return;
    const cache = readLocalHistoryCache();
    cache[sessionId] = list;
    writeLocalHistoryCache(cache);
  },
  { deep: true }
);
</script>

<style scoped lang="scss">
.chat-shell {
  flex: 1;
  display: flex;
  flex-direction: row;
  justify-content: center;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  position: relative;

  &.editor-open {
    .main-content {
      width: 44.7%;
    }

    :deep(.bottom-area) .bottom-area-inner {
      padding: 20px 16px;
    }

    :deep(.task-progress-anchor) {
      padding: 0 16px;
    }
  }
}

.main-content {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  position: relative;
  background: transparent;
  overflow: hidden;
  min-width: 0;
}

.input-stack {
  position: relative;
}

.task-progress-anchor {
  position: absolute;
  left: 50%;
  bottom: calc(100% - 8px);
  transform: translateX(-50%);
  width: 100%;
  max-width: 760px;
  z-index: 1001;
}

.linked-editor-shell {
  flex: 1;
  min-height: 0;
  height: 100%;
  z-index: 10;
}

.linked-editor-aside {
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #ffffff;
  border-radius: 24px;
  box-shadow: -10px 0 36px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.linked-editor-enter-active,
.linked-editor-leave-active {
  transition:
    flex-basis 0.34s cubic-bezier(0.4, 0, 0.2, 1),
    max-width 0.34s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.34s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.28s ease;
}

.linked-editor-enter-active .linked-editor-aside,
.linked-editor-leave-active .linked-editor-aside {
  transition: transform 0.34s cubic-bezier(0.4, 0, 0.2, 1);
}

.linked-editor-enter-from,
.linked-editor-leave-to {
  flex-basis: 0 !important;
  width: 0 !important;
  max-width: 0 !important;
  border-left-width: 0;
  opacity: 0;
}

.linked-editor-enter-from .linked-editor-aside,
.linked-editor-leave-to .linked-editor-aside {
  transform: translateX(100%);
}

.linked-editor-enter-to .linked-editor-aside,
.linked-editor-leave-from .linked-editor-aside {
  transform: translateX(0);
}

.main-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow-y: auto;
  padding: 30px 0 48px;
  height: calc(100% - 172px);
  gap: 0;

  &::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  &::-webkit-scrollbar-thumb {
    background: rgba(94, 94, 94, 0.22);
    border-radius: 999px;
  }
}
</style>
