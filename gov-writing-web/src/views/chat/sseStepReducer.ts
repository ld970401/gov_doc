/**
 * SSE 事件 → ChatMessage.steps 的归并器（reducer）。
 *
 * 设计要点：
 * 1. 协议直接对齐 `修改.txt`：
 *    - content_block_start：根据 `block.type + skillName + purpose` 决定阶段
 *    - content_block_delta：正文增量在 `event.delta.text`
 *    - content_block_stop ：阶段产物在 `event.payload`
 *    - message_stop       ：把残留的进行中任务一次性置 completed
 * 2. 不与旧协议做兼容，所有旧字段（plan/agent_use/plan_result/agent_result/text_delta）都不再处理。
 * 3. 状态机由 `activeBlock` 驱动，转移图：
 *
 *        start(a2a_planning)            stop(a2a_planning)
 *    null ───────────────────► planning ──────────────────► null
 *
 *        start(retrieval)               stop(retrieval)
 *    null ───────────────────► retrieval ─────────────────► null
 *
 *        start(text/article_draft)      stop(writing)
 *    null ───────────────────► writing ──────────────────► null
 *
 *    每个阶段最多对应 stepList 里的两条 step：一条 common（用于显示 loading），
 *    一条业务 step（PlanText / SearchResult / Document），由 stop 派生或在 start 时一并创建。
 */

import type {
  ContentBlockDeltaEvent,
  ContentBlockStartEvent,
  ContentBlockStopEvent,
  PlanStep,
  StreamEvent,
  TextBlock,
  ToolStopPayload,
  ToolUseBlock,
} from '@/api/chat';

/** 当前正在流的业务阶段。null 表示无活跃块（已 stop 或尚未 start）。 */
type ActiveBlock = 'planning' | 'retrieval' | 'writing' | null;

/** 从 data.md：写作 delta 为 { type, text }；也兼容仅含 text 的对象。 */
const extractWritingDeltaText = (delta: ContentBlockDeltaEvent['delta']): string => {
  if (delta == null) return '';
  if (typeof delta === 'string') return delta;
  if (typeof delta !== 'object') return '';
  const o = delta as Record<string, unknown>;
  if (typeof o.text === 'string') return o.text;
  return '';
};

/** 任务进度卡里单个任务的状态，与 TaskProgressCard.TaskItem 对齐。 */
type TaskStatus = 'pending' | 'in_progress' | 'completed';
interface ProgressTask {
  id: string;
  title: string;
  status: TaskStatus;
}

interface ReducerState {
  activeBlock: ActiveBlock;
  /** 当前阶段对应的 common step 在 stepList 中的下标（loading/标题占位）。 */
  activeCommonStepIndex: number | null;
  /** 写作阶段对应的 documentOutput step 下标，用于 delta 落点。 */
  activeDocStepIndex: number | null;
  /** 规划阶段产生的 PlanText step 下标，stop 时用于一次性写 summary。 */
  planTextStepIndex: number | null;
  /** 任务进度 step 下标。同一条消息只创建一次，由 a2a_planning stop 创建。 */
  taskProgressStepIndex: number | null;
  /** 当前 in_progress 的任务下标，用于 retrieval/writing stop 时推进。 */
  activeTaskIndex: number | null;
}

// ---------- 工厂函数：创建各种 step 模板 ----------

const makeClientId = (prefix: string) =>
  `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;

/** loading 占位 step：每个阶段开头都会先 push 一条，stop 时置 completed。 */
const createCommonStep = (label: string, icon: 'brain' | 'search' | 'pen'): Step => ({
  type: 'common',
  label,
  icon,
  status: 'loading',
  contentType: 'text',
  streaming: true,
  clientStepId: makeClientId('common'),
});

/** 规划阶段的展示卡，使用 planText 类型交给 PlanTextStep 渲染。 */
const createPlanTextStep = (): Step => ({
  type: 'planText',
  label: '规划内容',
  content: null,
  contentType: 'pre',
  streaming: true,
  clientStepId: makeClientId('plan-text'),
});

/** 写作阶段的文档卡：delta 持续写入 content.body，stop 时用 normalizedResult.document 覆盖。 */
const createDocumentStep = (): Step => ({
  type: 'document',
  label: '生成文档',
  content: { body: '' },
  contentType: 'documentCard',
  streaming: true,
  clientStepId: makeClientId('doc'),
});

const markStepCompleted = (step: Step | undefined) => {
  if (!step) return;
  step.status = 'completed';
  step.streaming = false;
};

/**
 * 创建归并器实例，绑定到一条 assistant 消息的 stepList。
 * 同一条消息只 new 一次；切换消息要重新调用本函数。
 */
export const createSseStepReducer = (stepList: Step[]) => {
  const state: ReducerState = {
    activeBlock: null,
    activeCommonStepIndex: null,
    activeDocStepIndex: null,
    planTextStepIndex: null,
    taskProgressStepIndex: null,
    activeTaskIndex: null,
  };

  // ---------- 任务进度卡的读写工具 ----------

  const getProgressTasks = (): ProgressTask[] => {
    if (state.taskProgressStepIndex === null) return [];
    const step = stepList[state.taskProgressStepIndex];
    if (!step || !step.content || typeof step.content !== 'object') return [];
    const raw = (step.content as { tasks?: ProgressTask[] }).tasks;
    return Array.isArray(raw) ? raw : [];
  };

  const setProgressTasks = (tasks: ProgressTask[]) => {
    if (state.taskProgressStepIndex === null) return;
    const step = stepList[state.taskProgressStepIndex];
    if (!step) return;
    const base = step.content && typeof step.content === 'object' ? step.content : {};
    step.content = {
      ...(base as Record<string, unknown>),
      tasks,
    };
    // 注意：这里不能把该 step 的 streaming 重新置为 true。
    // AgentSteps 的逐步展示依赖 "当前步骤 streaming-complete" 事件推进；
    // 规划卡（planText）若因任务状态被反向改回 streaming=true，会卡住后续检索/写作步骤不展示。
    // 任务卡头部的 loading/完成态由 tasks.status 自身决定，不依赖 step.streaming。
  };

  const completeActiveTaskAndMoveNext = () => {
    const tasks = getProgressTasks();
    if (!tasks.length) return;
    if (state.activeTaskIndex !== null && tasks[state.activeTaskIndex]) {
      tasks[state.activeTaskIndex].status = 'completed';
    }
    const nextIdx = tasks.findIndex((task) => task.status === 'pending');
    if (nextIdx >= 0) {
      tasks[nextIdx].status = 'in_progress';
      state.activeTaskIndex = nextIdx;
    } else {
      state.activeTaskIndex = null;
    }
    setProgressTasks(tasks);
  };

  const completeAllTasks = () => {
    const tasks = getProgressTasks();
    if (!tasks.length) return;
    tasks.forEach((task) => {
      task.status = 'completed';
    });
    state.activeTaskIndex = null;
    setProgressTasks(tasks);
  };

  // ---------- 各事件处理 ----------

  /**
   * content_block_start：根据 block 的 type/skillName/purpose 切换阶段，
   * 并预先 push 对应的 step 占位（common 必有，文档卡仅写作阶段需要）。
   */
  const handleStart = (event: ContentBlockStartEvent) => {
    const block = event.content_block;
    if (!block || typeof block !== 'object') return;

    const blockKind = String((block as { type?: string }).type || '')
      .toLowerCase()
      .replace(/-/g, '_');
    // 简单回答链路中的思考块：不展示、不落步骤（见 data.md）。
    if (blockKind === 'thinking') return;

    // 规划阶段：tool_use + skillName=a2a_planning。
    // 此阶段没有 delta，正文（summary/steps）会在 stop 时一次性给到。
    // 注意：规划详情卡片是否展示取决于 plan steps 数量，因此这里不提前创建 PlanText。
    if (block.type === 'tool_use' && (block as ToolUseBlock).skillName === 'a2a_planning') {
      const tu = block as ToolUseBlock;
      stepList.push(createCommonStep(tu.displayText || 'Leader Agent 正在规划中', 'brain'));
      state.activeCommonStepIndex = stepList.length - 1;
      state.planTextStepIndex = null;

      state.activeDocStepIndex = null;
      state.activeBlock = 'planning';
      return;
    }

    // 检索阶段：tool_use + skillName=retrieval。
    // 该阶段也没有 delta，items 会在 stop 时给到。
    if (block.type === 'tool_use' && (block as ToolUseBlock).skillName === 'retrieval') {
      const tu = block as ToolUseBlock;
      stepList.push(createCommonStep(tu.displayText || '正在检索资料', 'search'));
      state.activeCommonStepIndex = stepList.length - 1;
      state.activeDocStepIndex = null;
      state.activeBlock = 'retrieval';
      return;
    }

    // 简单回答：tool_use + skillName=general 不展示「进行中：主 Agent 对话」common，
    // 仅等 content_block_stop（main_agent）用 normalizedResult.text 一条回答（handleMainAgentStop）。

    // 写作阶段：注意是 type=text + purpose=article_draft（skillName=writing），
    // 不是 tool_use。这里同时创建 common + documentOutput，delta 写到 documentOutput.body。
    const blockType = typeof (block as { type?: string }).type === 'string' ? (block as { type: string }).type : '';
    if (blockType === 'text' || String(blockType).toLowerCase() === 'text') {
      const tb = block as TextBlock;
      const isWriting = tb.skillName === 'writing' || tb.purpose === 'article_draft';
      if (!isWriting) return;

      stepList.push(createCommonStep(tb.displayText || '正在撰写公文', 'pen'));
      state.activeCommonStepIndex = stepList.length - 1;

      stepList.push(createDocumentStep());
      state.activeDocStepIndex = stepList.length - 1;
      state.activeBlock = 'writing';
      return;
    }

    // 未知 skill：不创建任何 step，避免污染 UI；后续 stop 仍然会兜底完结。
  };

  /**
   * content_block_delta：仅写作阶段会推送，正文挂在 event.delta.text。
   * 历史协议中 delta 在 event.content_block.content，这里不做兼容。
   */
  const handleDelta = (event: ContentBlockDeltaEvent) => {
    const rawDelta = event.delta;
    if (rawDelta && typeof rawDelta === 'object') {
      const dt = String((rawDelta as Record<string, unknown>).type || '')
        .toLowerCase()
        .replace(/-/g, '_');
      if (dt === 'thinking_delta') return;
    }
    const text = extractWritingDeltaText(event.delta);
    if (!text) return;
    if (state.activeBlock !== 'writing' || state.activeDocStepIndex === null) return;

    const target = stepList[state.activeDocStepIndex];
    if (!target) return;
    const raw = (
      target.content && typeof target.content === 'object' ? target.content : { body: '' }
    ) as { body?: string };
    raw.body = `${raw.body || ''}${text}`;
    target.content = raw;
  };

  /**
   * content_block_stop：按 payload.tool 派生最终结构。
   * 不论何种阶段，都先把 common / docOutput / planText 的进行中态置 completed。
   */
  const handleStop = (event: ContentBlockStopEvent) => {
    const payload = event.payload;

    if (state.activeCommonStepIndex !== null) {
      markStepCompleted(stepList[state.activeCommonStepIndex]);
    }
    if (state.activeBlock === 'writing' && state.activeDocStepIndex !== null) {
      markStepCompleted(stepList[state.activeDocStepIndex]);
    }
    if (state.activeBlock === 'planning' && state.planTextStepIndex !== null) {
      markStepCompleted(stepList[state.planTextStepIndex]);
    }

    if (payload) {
      switch (payload.tool) {
        case 'a2a_planning':
          handlePlanningStop(payload);
          break;
        case 'retrieval':
          handleRetrievalStop(payload);
          completeActiveTaskAndMoveNext();
          break;
        case 'writing':
          handleWritingStop(payload);
          completeActiveTaskAndMoveNext();
          break;
        case 'main_agent':
          handleMainAgentStop(payload);
          break;
        default:
          // 未知工具：仅标记 common step 完成，不再追加业务 step。
          break;
      }
    }

    state.activeBlock = null;
    state.activeCommonStepIndex = null;
    state.activeDocStepIndex = null;
  };

  /**
   * 规划完成：把 plan.summary + steps 一次性写入 PlanText step，
   * 并基于 plan.steps 建立任务进度卡。注意规划本身不计入任务推进。
   */
  const handlePlanningStop = (payload: ToolStopPayload) => {
    const planSteps: PlanStep[] = Array.isArray(payload.plan?.steps)
      ? (payload.plan!.steps as PlanStep[])
      : [];
    const declaredStepCount = typeof payload.steps === 'number' ? payload.steps : planSteps.length;

    // 规则：规划只有 1 步（如仅“检索资料”或仅“公文写作”）时，
    // 不展示规划相关卡片（包括 planning common 行与 PlanTextStep），直接进入任务执行。
    if (planSteps.length <= 1 || declaredStepCount <= 1) {
      if (state.activeCommonStepIndex !== null && stepList[state.activeCommonStepIndex]) {
        stepList.splice(state.activeCommonStepIndex, 1);
      }
      state.taskProgressStepIndex = null;
      state.activeTaskIndex = null;
      state.planTextStepIndex = null;
      return;
    }

    const planStep = createPlanTextStep();
    // 直接保留后端 payload 结构，PlanTextStep 负责解析展示字段。
    planStep.content = payload;
    planStep.status = 'completed';
    planStep.streaming = false;
    stepList.push(planStep);
    state.planTextStepIndex = stepList.length - 1;

    const tasks: ProgressTask[] = planSteps.map((s, idx) => ({
      // displayTitle 可能被后端截断，这里优先用 title。
      title: s.title || s.displayTitle || `任务 ${idx + 1}`,
      // 按 skillName + index 生成稳定 id，便于后续按 stepIndex 精确推进。
      id: `${s.skillName || 'task'}-${s.index ?? idx + 1}`,
      status: idx === 0 ? 'in_progress' : 'pending',
    }));
    state.taskProgressStepIndex = state.planTextStepIndex;
    state.activeTaskIndex = tasks.length > 0 ? 0 : null;
    setProgressTasks(tasks);
  };

  /** 检索完成：把 normalizedResult.items 渲染为 searchResult step。 */
  const handleRetrievalStop = (payload: ToolStopPayload) => {
    const items = Array.isArray(payload.normalizedResult?.items)
      ? payload.normalizedResult!.items!
      : [];
    stepList.push({
      type: 'searchResult',
      label: '检索结果',
      content: {
        title: '检索结果',
        // 描述文案直接显示数量，避免硬编码长句。
        description: items.length ? `共 ${items.length} 条相关文件` : '',
        articles: items.map((item) => ({
          title: item.title || '',
          description: item.description || '',
          // 后端目前未提供 url，组件层会按空值兜底，这里如实透传。
          url: item.url || '',
        })),
      },
      contentType: 'searchResult',
      streaming: false,
      clientStepId: makeClientId('search'),
    });
  };

  /**
   * 写作完成：用 normalizedResult.document 覆盖累计 delta，
   * 兜底中文跨切片或网络抖动导致的拼接错位。
   */
  const handleWritingStop = (payload: ToolStopPayload) => {
    const finalDoc = payload.normalizedResult?.document;
    if (typeof finalDoc !== 'string' || !finalDoc) return;
    if (state.activeDocStepIndex === null) return;
    const target = stepList[state.activeDocStepIndex];
    if (!target) return;
    const base = (
      target.content && typeof target.content === 'object' ? target.content : {}
    ) as Record<string, unknown>;
    target.content = { ...base, body: finalDoc };
  };

  /**
   * 主 Agent 直答（见 data.md）：content_block_stop payload.tool=main_agent，
   * 正文在 normalizedResult.text，对应 PlainTextStep（type=text）。
   */
  const handleMainAgentStop = (payload: ToolStopPayload) => {
    const finalText = payload.normalizedResult?.text;
    if (typeof finalText !== 'string' || !finalText) return;
    stepList.push({
      type: 'text',
      label: '回答',
      content: finalText,
      contentType: 'text',
      status: 'completed',
      streaming: false,
      clientStepId: makeClientId('main-agent'),
    });
  };

  return {
    /**
     * 根据事件类型分发到对应处理器。
     * 上层（index.vue）只需要把每条事件透传过来即可，不需要关心阶段语义。
     */
    apply(event: StreamEvent) {
      switch (event.type) {
        case 'content_block_start':
          handleStart(event as ContentBlockStartEvent);
          break;
        case 'content_block_delta':
          handleDelta(event as ContentBlockDeltaEvent);
          break;
        case 'content_block_stop':
          handleStop(event as ContentBlockStopEvent);
          break;
        case 'message_stop':
          // 兜底：把任务卡里残留的 in_progress / pending 全部置 completed。
          completeAllTasks();
          break;
        default:
          break;
      }
    },
  };
};
