import request from '@/utils/request';

export interface AgentloopUser {
  userId: string;
  account: string;
  name: string;
  orgName?: string;
  orgCode?: string;
  authModels: Array<{ modelName: string; modelDisplayName: string }>;
  defaultModel: string;
  isFirstLoginToAgentloop?: boolean;
  preferredSkills?: string[];
  recommendationSummary?: string;
  identifyMarkdown?: string;
  memoryMarkdown?: string;
  sessionSummaryMarkdown?: string;
  legacySystemUrl?: string;
}

type ApiEnvelope<T> = { code: number; message: string; data: T };

/** GET /me（baseURL 已为 /api/agentloop） */
export async function getMe(): Promise<AgentloopUser | null> {
  try {
    const res = (await request.get('/me')) as unknown as ApiEnvelope<AgentloopUser>;
    if (res?.data) return res.data;
    return null;
  } catch {
    return null;
  }
}
