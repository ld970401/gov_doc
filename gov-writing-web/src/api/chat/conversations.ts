import request from '@/utils/request';

type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export interface ConversationListItem {
  id: string;
  title: string;
  pinned: boolean;
  updatedAt: string;
  lastRunId?: string;
  meta?: string;
}

export interface ConversationMessage {
  id: string;
  runId?: string;
  role: 'user' | 'assistant' | 'system';
  skillName?: string;
  /** 会话详情多为结构化对象；旧数据可能为 JSON 字符串或纯文本 */
  content?: string | Record<string, unknown>;
  contentHtml?: string;
  model?: string;
  annotations?: unknown[];
  meta?: Record<string, unknown>;
  createdAt: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  pinned: boolean;
  messages: ConversationMessage[];
}

export interface RunPayload {
  content: string;
  model?: string;
  skill?: string | null;
  attachments?: string[];
  resume_from_waiting?: boolean;
  selected_option?: string;
  prompt_menu_input?: string;
}

export interface RunResponse {
  conversationId: string;
  conversationTitle: string;
  runId: string;
  taskId: string;
  streamUrl: string;
}

export async function listConversations(): Promise<ConversationListItem[]> {
  const res = (await request.get('/conversations')) as ApiEnvelope<ConversationListItem[]>;
  return Array.isArray(res.data) ? res.data : [];
}

export async function getConversationDetail(conversationId: string): Promise<ConversationDetail> {
  const res = (await request.get(
    `/conversations/${conversationId}`
  )) as ApiEnvelope<ConversationDetail>;
  return res.data;
}

export async function updateConversation(
  conversationId: string,
  payload: { title?: string; pinned?: boolean }
): Promise<boolean> {
  await request.patch(`/conversations/${conversationId}`, payload);
  return true;
}

export async function deleteConversation(conversationId: string): Promise<boolean> {
  await request.delete(`/conversations/${conversationId}`);
  return true;
}

export async function runNewConversation(payload: RunPayload): Promise<RunResponse> {
  const res = (await request.post('/conversations/run', payload)) as ApiEnvelope<RunResponse>;
  return res.data;
}

export async function runConversation(
  conversationId: string,
  payload: RunPayload
): Promise<RunResponse> {
  const res = (await request.post(
    `/conversations/${conversationId}/run`,
    payload
  )) as ApiEnvelope<RunResponse>;
  return res.data;
}
