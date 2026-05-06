import request from '@/utils/request';

type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export interface ModelItem {
  id: string;
  label: string;
}

export async function listModels(): Promise<ModelItem[]> {
  const res = (await request.get('/models')) as ApiEnvelope<ModelItem[]>;
  return Array.isArray(res.data) ? res.data : [];
}

export interface SkillItem {
  key: string;
  title: string;
  summary: string;
  example: string;
  examples: string[];
}

export async function listSkills(): Promise<SkillItem[]> {
  const res = (await request.get('/skills')) as ApiEnvelope<SkillItem[]>;
  return Array.isArray(res.data) ? res.data : [];
}
