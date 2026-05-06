// 全局类型声明
export { };

declare global {
  interface ChatSession {
    id: string;
    title: string;
    subtitle?: string;
    pinned: boolean;
    isNew?: boolean;
    createdAt: string;
    updatedAt: string;
  }

  interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    createdAt: string;
    attachment?: unknown;
    skill?: string | null;
    /** assistant 的步骤流，按渲染顺序 append。 */
    steps?: Step[];
    text?: string;
    textVisible?: boolean;
    streaming?: boolean;
    decisionPrompt?: {
      prompt: string;
      description?: string;
      options: Array<{
        id: string;
        label: string;
        variant?: 'default' | 'primary' | 'ghost';
        sendText?: string;
      }>;
    };
  }

  interface ChatSessionDetail extends ChatSession {
    messages: ChatMessage[];
  }

  type StepType =
    | 'common'
    | 'text'
    | 'tool'
    | 'template'
    | 'document'
    | 'reportCard'
    | 'tableCard'
    | 'text'
    | 'searchResult'
    | 'result';

  type StepContentType =
    | 'text'
    | 'search'
    | 'pre'
    | 'json'
    | 'html'
    | 'skills'
    | 'template'
    | 'documentCard'
    | 'reportCard'
    | 'tableCard'
    | 'text'
    | 'searchResult'
    | 'result';

  interface Step {
    id?: string;
    type: StepType;
    label?: string;
    content?: any;
    contentType?: StepContentType;
    open?: boolean;
    timestamp?: number;
    streaming?: boolean;
    status?: 'loading' | 'completed';
    icon?: 'brain' | 'search' | 'pen';
    clientStepId?: string;
    [key: string]: unknown;
  }

  interface StepContent {
    total?: number;
    used?: number;
    summary?: string;
    skills?: string[];
    results?: unknown[];
  }

  interface ApiResponse<T = unknown> {
    code: 200 | 400 | 404 | 500;
    message: string;
    data: T;
  }

  interface PaginatedResponse<T> {
    total: number;
    page: number;
    pageSize: number;
    list: T[];
  }
}
