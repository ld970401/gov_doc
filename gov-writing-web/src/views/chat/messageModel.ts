import type { ConversationMessage } from '@/api/chat/conversations';
import type { PlanStep } from '@/api/chat';

export type BackendMessage = ConversationMessage;

export const createEmptySteps = (): Step[] => [];

const makeClientId = (prefix: string, seed: string) => `${prefix}-${seed}`;

/** 会话详情里单条执行步骤（与流式 stop 产物对齐） */
type DetailExecutionStep = {
  index?: number;
  taskId?: string;
  skillName?: string;
  title?: string;
  normalizedResult?: {
    items?: Array<{ title?: string; description?: string; url?: string }>;
    document?: string;
    text?: string;
    source?: string;
  };
};

function normalizeContent(raw: ConversationMessage['content']): Record<string, unknown> | string | null {
  if (raw == null) return null;
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === 'object') return parsed as Record<string, unknown>;
    } catch {
      /* 纯文本 */
    }
    return raw;
  }
  return null;
}

function extractUserDisplayText(normalized: Record<string, unknown> | string | null): string {
  if (normalized === null) return '';
  if (typeof normalized === 'string') return normalized;
  if (typeof normalized.text === 'string') return normalized.text;
  return '';
}

/**
 * 将详情接口中的 assistant.content 还原为与 SSE reducer 一致的 Step[]，
 * 便于 AgentSteps / DocumentStep / SearchResultStep 等与流式结束后一致。
 */
export function buildAssistantStepsFromDetailContent(
  messageId: string,
  raw: Record<string, unknown>
): Step[] {
  const stepsOut: Step[] = [];
  const planIntent = typeof raw.planIntent === 'string' ? raw.planIntent : '';
  const planSummary = typeof raw.planSummary === 'string' ? raw.planSummary : '';
  const execSteps = Array.isArray(raw.steps) ? (raw.steps as DetailExecutionStep[]) : [];

  const topLevelText =
    typeof raw.text === 'string'
      ? raw.text
      : typeof (raw as { normalizedResult?: { text?: string } }).normalizedResult?.text === 'string'
        ? (raw as { normalizedResult: { text: string } }).normalizedResult.text
        : '';

  if (execSteps.length === 0) {
    if (topLevelText) {
      stepsOut.push({
        type: 'text',
        label: '回答',
        content: topLevelText,
        contentType: 'text',
        status: 'completed',
        streaming: false,
        clientStepId: makeClientId('hist-text', messageId),
      });
    }
    return stepsOut;
  }

  const multiPlan = execSteps.length > 1;

  if (multiPlan) {
    const planStepsForCard: PlanStep[] = execSteps.map((s, idx) => ({
      index: typeof s.index === 'number' ? s.index : idx + 1,
      skillName: s.skillName || '',
      title: s.title || `步骤 ${idx + 1}`,
      displayTitle: s.title,
    }));

    const tasks = execSteps.map((s, idx) => ({
      id: s.taskId || `${s.skillName || 'task'}-${s.index ?? idx + 1}`,
      title: s.title || `任务 ${idx + 1}`,
      status: 'completed' as const,
    }));

    stepsOut.push({
      type: 'planText',
      label: '规划内容',
      content: {
        tool: 'a2a_planning',
        displayText: planSummary,
        plan: {
          intent: planIntent,
          summary: planSummary,
          steps: planStepsForCard,
        },
        tasks,
      },
      contentType: 'pre',
      streaming: false,
      status: 'completed',
      clientStepId: makeClientId('hist-plan', messageId),
    });
  }

  for (let i = 0; i < execSteps.length; i++) {
    const s = execSteps[i];
    const skill = String(s.skillName || '').toLowerCase();
    const seed = `${messageId}-${i}`;

    if (skill === 'retrieval') {
      stepsOut.push({
        type: 'common',
        label: '进行中：资料检索',
        icon: 'search',
        status: 'completed',
        contentType: 'text',
        streaming: false,
        clientStepId: makeClientId('hist-ret-common', seed),
      });
      const items = Array.isArray(s.normalizedResult?.items) ? s.normalizedResult!.items! : [];
      stepsOut.push({
        type: 'searchResult',
        label: '检索结果',
        content: {
          title: '检索结果',
          description: items.length ? `共 ${items.length} 条相关文件` : '',
          articles: items.map((item) => ({
            title: item.title || '',
            description: item.description || '',
            url: item.url || '',
          })),
        },
        contentType: 'searchResult',
        streaming: false,
        clientStepId: makeClientId('hist-ret-search', seed),
      });
    } else if (skill === 'writing') {
      stepsOut.push({
        type: 'common',
        label: '进行中：公文写作',
        icon: 'pen',
        status: 'completed',
        contentType: 'text',
        streaming: false,
        clientStepId: makeClientId('hist-wri-common', seed),
      });
      const doc = typeof s.normalizedResult?.document === 'string' ? s.normalizedResult.document : '';
      stepsOut.push({
        type: 'document',
        label: '生成文档',
        content: { body: doc },
        contentType: 'documentCard',
        streaming: false,
        status: 'completed',
        clientStepId: makeClientId('hist-doc', seed),
      });
    } else if (skill === 'general') {
      const txt = typeof s.normalizedResult?.text === 'string' ? s.normalizedResult.text : '';
      if (txt) {
        stepsOut.push({
          type: 'text',
          label: '回答',
          content: txt,
          contentType: 'text',
          status: 'completed',
          streaming: false,
          clientStepId: makeClientId('hist-general', seed),
        });
      }
    } else {
      const nr = s.normalizedResult;
      const txt =
        typeof nr?.text === 'string'
          ? nr.text
          : typeof nr?.document === 'string'
            ? nr.document
            : '';
      if (txt) {
        stepsOut.push({
          type: 'text',
          label: '回答',
          content: txt,
          contentType: 'text',
          status: 'completed',
          streaming: false,
          clientStepId: makeClientId('hist-unknown', seed),
        });
      }
    }
  }

  return stepsOut;
}

export const mapBackendMessages = (list: ConversationMessage[] | undefined): ChatMessage[] => {
  if (!Array.isArray(list)) return [];
  return list
    .filter((msg) => msg.role === 'user' || msg.role === 'assistant')
    .map((msg) => {
      const normalized = normalizeContent(msg.content);

      if (msg.role === 'user') {
        return {
          id: msg.id,
          role: 'user' as const,
          content: extractUserDisplayText(normalized),
          skill: msg.skillName ?? null,
          createdAt: msg.createdAt,
          streaming: false,
        };
      }

      const obj =
        normalized !== null && typeof normalized === 'object' && !Array.isArray(normalized)
          ? (normalized as Record<string, unknown>)
          : null;

      let steps = obj ? buildAssistantStepsFromDetailContent(msg.id, obj) : [];

      const plainFallback =
        typeof normalized === 'string'
          ? normalized
          : obj && typeof obj.text === 'string'
            ? obj.text
            : '';

      const htmlFallback = msg.contentHtml || '';

      if (!steps.length && (plainFallback || htmlFallback)) {
        const textBody = htmlFallback || plainFallback;
        steps = [
          {
            type: 'text',
            label: '回答',
            content: textBody,
            contentType: 'text',
            status: 'completed',
            streaming: false,
            clientStepId: makeClientId('hist-fallback', msg.id),
          },
        ];
      }

      const assistantSummary =
        obj && typeof obj.planSummary === 'string'
          ? obj.planSummary
          : plainFallback.slice(0, 240);

      return {
        id: msg.id,
        role: 'assistant' as const,
        content: assistantSummary || plainFallback.slice(0, 240),
        /** 有结构化 steps 时不再走气泡，避免与 PlainTextStep 重复 */
        text:
          steps.length > 0
            ? undefined
            : htmlFallback || plainFallback
              ? htmlFallback || plainFallback
              : undefined,
        textVisible: steps.length > 0 ? undefined : true,
        createdAt: msg.createdAt,
        streaming: false,
        steps,
      };
    });
};
