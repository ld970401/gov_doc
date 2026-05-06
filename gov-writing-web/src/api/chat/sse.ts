/**
 * SSE 事件协议（与后端 `修改.txt` 样例保持一致）。
 *
 * 一条 SSE 流大致按如下顺序发送：
 *   1) message_start
 *   2) content_block_start (tool_use|text)
 *      - tool_use + skillName=a2a_planning   规划阶段
 *      - tool_use + skillName=retrieval      检索阶段
 *      - text     + purpose=article_draft    写作阶段
 *   3) content_block_delta (delta.text)      仅写作阶段会持续推送
 *   4) content_block_stop  (payload.tool=...) 阶段结束，附带 plan / normalizedResult
 *   5) message_stop
 *   6) data: [DONE]                          流终止哨兵，非 JSON
 *
 * 注：本文件不做兼容旧协议的处理，所有字段都来自新协议。
 */

/** 工具调用块：用于规划（a2a_planning）/ 检索（retrieval）等非纯文本阶段。 */
export interface ToolUseBlock {
  type: 'tool_use';
  /** 后端定义的技能名，决定该块属于哪个阶段。 */
  skillName: 'a2a_planning' | 'retrieval' | string;
  /** UI 直接展示的进行中文案，例如「进行中：资料检索」。 */
  displayText?: string;
}

/**
 * 纯文本块：写作阶段使用。注意写作阶段不是 tool_use，
 * 而是 type=text + purpose=article_draft + skillName=writing。
 */
export interface TextBlock {
  type: 'text';
  /** 文本用途，目前仅观测到 `article_draft`（公文正文）。 */
  purpose?: 'article_draft' | string;
  /** 写作阶段的 skillName 固定为 `writing`。 */
  skillName?: 'writing' | string;
  /** UI 直接展示的进行中文案，例如「进行中：公文写作」。 */
  displayText?: string;
}

export type ContentBlock = ToolUseBlock | TextBlock;

/** 写作阶段每次推送的增量文本载体。 */
export interface TextDelta {
  type: 'text_delta';
  text: string;
}

/** 简单回答中可能出现的思考流（见 data.md）。 */
export interface ThinkingDelta {
  type: 'thinking_delta';
  thinking: string;
}

/** 规划完成后返回的执行步骤定义，用于驱动右侧任务进度卡。 */
export interface PlanStep {
  /** 1 起始的步骤序号。 */
  index: number;
  /** 该步骤后续会用什么 skill 来执行（retrieval / writing / ...）。 */
  skillName: string;
  /** 短标题，适合做任务卡名称。 */
  title: string;
  /** 完整描述，可能被后端截断，仅用于 tooltip。 */
  displayTitle?: string;
  /** 依赖的前置步骤 id 列表。 */
  dependsOn?: string[];
  /** 子任务角色，目前观测到 `skill_worker`。 */
  subtaskRole?: string;
}

/**
 * content_block_stop 的语义载体。
 * 不同 tool 复用此 payload，但只会填写自己关心的字段：
 *   - a2a_planning: plan
 *   - retrieval:    normalizedResult.items
 *   - writing:      normalizedResult.document
 */
export interface ToolStopPayload {
  tool: 'a2a_planning' | 'retrieval' | 'writing' | string;
  skillName?: string;
  stepIndex?: number;
  stepTitle?: string;
  /** 完成态文案，例如「已完成：资料检索」。 */
  displayText?: string;
  retryable?: boolean;
  /** 来源标识，例如 `legacy_success` / `model_success`。 */
  sourceState?: 'legacy_success' | 'model_success' | string;
  /** 错误详情，正常完成时为 null。 */
  errorDetail?: unknown;
  /** 规划阶段：本次产出的步骤数量。 */
  steps?: number;
  /** 规划阶段产物：包含意图、摘要与执行步骤列表。 */
  plan?: {
    intent?: string;
    summary?: string;
    steps: PlanStep[];
  };
  /** 检索/写作阶段产物：检索条目或最终文档。 */
  normalizedResult?: {
    source?: string;
    items?: Array<{ title?: string; description?: string; url?: string }>;
    itemsTotal?: number;
    document?: string;
    /** 主 Agent 直答等场景的最终文本（见 data.md / main_agent stop）。 */
    text?: string;
  };
}

export interface StreamEventBase {
  type: string;
  [key: string]: unknown;
}

export interface MessageStartEvent extends StreamEventBase {
  type: 'message_start';
}

export interface ContentBlockStartEvent extends StreamEventBase {
  type: 'content_block_start';
  content_block?: ContentBlock;
}

export interface ContentBlockDeltaEvent extends StreamEventBase {
  type: 'content_block_delta';
  /** 注意：新协议中 delta 是顶层字段，不再嵌在 content_block 内部。 */
  delta?: TextDelta | ThinkingDelta | (Record<string, unknown> & { text?: string; thinking?: string });
}

export interface ContentBlockStopEvent extends StreamEventBase {
  type: 'content_block_stop';
  /** 阶段产物全部承载在 payload 上。 */
  payload?: ToolStopPayload;
}

export interface MessageDeltaEvent extends StreamEventBase {
  type: 'message_delta';
  delta?: { stop_reason?: string };
}

export interface MessageStopEvent extends StreamEventBase {
  type: 'message_stop';
}

export type StreamEvent =
  | MessageStartEvent
  | ContentBlockStartEvent
  | ContentBlockDeltaEvent
  | ContentBlockStopEvent
  | MessageDeltaEvent
  | MessageStopEvent
  | StreamEventBase;

export interface SSEHandlers {
  onEvent: (event: StreamEvent) => void;
  onDone: () => void;
  onError: (error: Error) => void;
}

/** 把后端可能出现的 kebab-case / 大小写差异，统一成下划线 ASCII。 */
const normalizeEventType = (rawType: unknown): string => {
  if (typeof rawType !== 'string') return '';
  return rawType.replace(/-/g, '_');
};

/**
 * 浅拷贝事件对象，避免下游 reducer 的可变操作影响 fetch 缓冲区里的原对象。
 * 同时对 `content_block` / `delta` / `payload` 三个嵌套对象再做一层浅拷贝。
 */
const normalizeStreamEvent = (raw: unknown): StreamEvent | null => {
  if (!raw || typeof raw !== 'object') return null;
  const event = { ...(raw as Record<string, unknown>) };
  event.type = normalizeEventType(event.type);

  const contentBlock = event.content_block;
  if (contentBlock && typeof contentBlock === 'object') {
    const nextBlock = { ...(contentBlock as Record<string, unknown>) };
    nextBlock.type = normalizeEventType(nextBlock.type);
    event.content_block = nextBlock;
  }

  const delta = event.delta;
  if (delta && typeof delta === 'object') {
    const nextDelta = { ...(delta as Record<string, unknown>) };
    if (typeof nextDelta.type === 'string') {
      nextDelta.type = normalizeEventType(nextDelta.type);
    }
    event.delta = nextDelta;
  }

  const payload = event.payload;
  if (payload && typeof payload === 'object') {
    event.payload = { ...(payload as Record<string, unknown>) };
  }

  return event as StreamEvent;
};

/**
 * 建立一条 SSE 长连接。
 *
 * 解析约定：
 *   - 每条事件以两个换行 `\n\n` 分隔（标准 EventStream 行为）；
 *   - 每行以 `data:` 开头，data 内容直接 JSON.parse；
 *   - 例外：`data: [DONE]` 是流终止哨兵，非 JSON，必须显式跳过。
 */
export function createSSEConnection(
  streamUrl: string,
  handlers: SSEHandlers
): { close: () => void } {
  const controller = new AbortController();

  const splitBuffer = (buffer: string) => {
    const blocks = buffer.split('\n\n');
    return {
      rest: blocks.pop() || '',
      blocks,
    };
  };

  void fetch(streamUrl, {
    credentials: 'include',
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok || !response.body) {
        throw new Error(`SSE 连接失败: ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          handlers.onDone();
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parsed = splitBuffer(buffer);
        buffer = parsed.rest;

        for (const block of parsed.blocks) {
          const lines = block.split('\n');
          const dataLines = lines
            .map((line) => line.trim())
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim());
          if (!dataLines.length) continue;
          const dataText = dataLines.join('\n');

          // 流终止哨兵：后端在最后一条 message_stop 之后发送 `data: [DONE]`，
          // 它不是 JSON，需要显式跳过，否则会进入下方的 catch 被静默吞掉。
          if (dataText === '[DONE]') continue;

          try {
            const parsedEvent = normalizeStreamEvent(JSON.parse(dataText));
            if (parsedEvent) handlers.onEvent(parsedEvent);
          } catch {
            // 极端情况下可能收到非 JSON 片段（半截 chunk），忽略即可。
          }
        }
      }
    })
    .catch((error: unknown) => {
      if ((error as { name?: string }).name === 'AbortError') return;
      handlers.onError(error instanceof Error ? error : new Error('SSE 连接异常'));
    });

  return {
    close: () => controller.abort(),
  };
}
