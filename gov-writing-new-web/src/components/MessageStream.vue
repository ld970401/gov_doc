<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { marked } from "marked";
import StepTimeline from "@/components/StepTimeline.vue";
import { state, submitFeedback } from "@/store";

marked.use({ breaks: true, gfm: true });

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  events: {
    type: Array,
    default: () => [],
  },
  artifacts: {
    type: Array,
    default: () => [],
  },
  /** 主 Agent 规划阶段流式推理（与步骤时间线并行展示） */
  plannerStreamingText: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["open-artifact", "regenerate", "suggest-cli"]);

const streamEl = ref(null);
const copiedIds = ref(new Set());

const latestAssistantId = computed(() => {
  const last = [...props.messages].reverse().find((item) => item.role === "assistant");
  return last?.id || "";
});

/** 详情接口：用户/助手都支持 `{ text, ... }`；流式仍为字符串 */
function plainMessageContent(message) {
  const c = message?.content;
  if (typeof c === "string") {
    return c;
  }
  if (c && typeof c === "object") {
    if (c.text != null) {
      return String(c.text);
    }
  }
  return "";
}

function stripHtml(html) {
  return String(html || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|blockquote|tr)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** 将模型常用「•」项目符号转为 Markdown 列表，便于 marked 识别 */
function normalizeListMarkers(text) {
  return String(text || "").replace(/(^|\n)\s*[•·]\s+/g, "$1- ");
}

/** 正文是否含 Markdown 语法（后端 text_to_html 常把 ** 原样放在 <p> 里，需走 marked） */
function looksLikeMarkdown(text) {
  const s = String(text || "");
  return (
    /\*\*[^\s*]/.test(s) ||
    /(^|\n)\s*#{1,6}\s/.test(s) ||
    /(^|\n)\s*[-*+]\s+\S/m.test(s) ||
    /(^|\n)\s*\d+\.\s+\S/m.test(s) ||
    /(^|\n)>\s/.test(s) ||
    /`[^`\n]+`/.test(s) ||
    /(^|\n)\s{0,3}```/.test(s) ||
    /(^|\n)\s*[•·]\s+\S/m.test(s)
  );
}

/** 明显为后端拼好的结构化 HTML（无未渲染 MD 时）再原样输出 */
function isStructuredAssistantHtml(html) {
  const raw = html || "";
  if (!raw.trim()) {
    return false;
  }
  return (
    /assistant-block|planner-stream-panel|writing-thought|reasoning-panel/i.test(raw) ||
    /<section\b/i.test(raw) ||
    /<table\b/i.test(raw)
  );
}

/**
 * 渲染助手正文：优先 Markdown（与后端 <p> 内仍含 ** 的情况兼容）。
 * 注意：content 常为短标题（如「主 Agent 回复」），不可优先于 contentHtml 长正文。
 */
function renderMd(html, plainText) {
  const raw = html || "";
  const stripped = stripHtml(raw);
  const plain = (plainText && String(plainText).trim()) || "";
  const candidate = stripped.length >= plain.length ? stripped : plain || stripped;

  if (!candidate && !raw) {
    return "<p></p>";
  }

  if (looksLikeMarkdown(candidate)) {
    return marked.parse(normalizeListMarkers(candidate));
  }

  if (raw && isStructuredAssistantHtml(raw) && !looksLikeMarkdown(candidate)) {
    return raw;
  }

  if (candidate) {
    return marked.parse(normalizeListMarkers(candidate));
  }

  return raw || "<p></p>";
}

function renderPlannerHtml(text) {
  const t = String(text || "");
  if (!t) {
    return "";
  }
  return marked.parse(t);
}

async function copyMessage(message) {
  const text = plainMessageContent(message) || stripHtml(message.contentHtml || "");
  try {
    await navigator.clipboard?.writeText(text);
    const next = new Set(copiedIds.value);
    next.add(message.id);
    copiedIds.value = next;
    window.setTimeout(() => {
      const n2 = new Set(copiedIds.value);
      n2.delete(message.id);
      copiedIds.value = n2;
    }, 1500);
  } catch {
    /* ignore */
  }
}

function feedbackFor(messageId) {
  return state.messageFeedbacks?.[messageId] ?? null;
}

async function toggleFeedback(message, type) {
  const cur = feedbackFor(message.id);
  const next = cur === type ? null : type;
  await submitFeedback(message.id, next);
}

function firstStepOutcome(message) {
  return message?.meta?.stepOutcomes?.[0] || null;
}

function messageSourceState(message) {
  const step = firstStepOutcome(message);
  return step?.source_state || step?.normalized_result?.source || "";
}

function sourceStateLabel(sourceState) {
  const mapping = {
    legacy_success: "旧接口成功",
    model_success: "模型成功",
    static_template: "静态模板",
    legacy_error: "旧接口失败",
    model_error: "模型失败",
  };
  return mapping[sourceState] || sourceState || "已完成";
}

function messageErrorDetail(message) {
  const step = firstStepOutcome(message);
  return step?.error_detail || message?.meta?.pendingPromptMenu?.errorDetail || "";
}

function shouldShowEvents(message) {
  return message.id === latestAssistantId.value && props.events.length > 0;
}

function historicalStepOutcomes(message) {
  return Array.isArray(message?.meta?.stepOutcomes) ? message.meta.stepOutcomes : [];
}

function shouldShowHistorySteps(message) {
  return !shouldShowEvents(message) && historicalStepOutcomes(message).length > 0;
}

function genericAssistantTitle(title) {
  return ["主 Agent 回复", "检索结果", "审核结果", "查重报告", "排版结果", "任务未执行", "执行失败"].includes(
    title || ""
  );
}

function reasoningSections(message) {
  const sections = [];
  const plannerReasoning = (message?.meta?.plannerReasoning || "").trim();
  if (plannerReasoning) {
    sections.push({
      key: "planner",
      title: "主 Agent 规划思路",
      content: plannerReasoning,
    });
  }
  for (const step of historicalStepOutcomes(message)) {
    const content = (step?.reasoning_content || "").trim();
    if (!content) {
      continue;
    }
    sections.push({
      key: `${step.task_id || step.title}-reasoning`,
      title: `${step.title || step.summary || "步骤"}的思路`,
      content,
    });
  }
  return sections;
}

function hasReasoning(message) {
  return reasoningSections(message).length > 0;
}

function messageHeadline(message) {
  const content = plainMessageContent(message).trim();
  if (content && !genericAssistantTitle(content) && content !== "执行中") {
    return content;
  }
  const firstStep = firstStepOutcome(message);
  if (firstStep?.summary && !genericAssistantTitle(firstStep.summary)) {
    return firstStep.summary;
  }
  const plain = stripHtml(message?.contentHtml || "");
  if (!plain) {
    return content || "智能体结果";
  }
  return plain.length > 60 ? `${plain.slice(0, 59).trim()}…` : plain;
}

function assistantStatusLabel(message) {
  if (shouldShowEvents(message)) {
    return "实时执行中";
  }
  return sourceStateLabel(messageSourceState(message));
}

let lastSuggestEmitFor = "";

function checkSuggestCli() {
  const last = [...props.messages].reverse().find((m) => m.role === "assistant");
  if (!last || last.id === lastSuggestEmitFor) {
    return;
  }
  const blob = `${plainMessageContent(last) || ""}${last.contentHtml || ""}`;
  if (/(云盘|工作区|文件列表|有哪些文件)/.test(blob)) {
    lastSuggestEmitFor = last.id;
    emit("suggest-cli");
  }
}

watch(
  () => props.messages,
  () => {
    checkSuggestCli();
  },
  { deep: true }
);

onMounted(() => {
  checkSuggestCli();
});
</script>

<template>
  <div ref="streamEl" class="message-stream" :class="{ 'has-messages': messages.length }">
    <div
      v-for="message in messages"
      :key="message.id"
      class="message-row"
      :class="message.role"
    >
      <div v-if="message.role === 'user'" class="user-bubble">
        <div class="user-bubble-label">
          <span class="material-symbols-rounded">person</span>
          用户
        </div>
        <p>{{ plainMessageContent(message) }}</p>
      </div>

      <article v-else class="assistant-card">
        <div class="assistant-header">
          <div class="assistant-meta">
            <div class="assistant-caption">{{ messageHeadline(message) }}</div>
          </div>
          <div class="assistant-status" :class="{ streaming: shouldShowEvents(message) }">
            <span class="pulse" />
            {{ assistantStatusLabel(message) }}
          </div>
        </div>

        <div v-if="plannerStreamingText && message.id === latestAssistantId" class="planner-stream-panel">
          <div class="planner-stream-label">
            <span class="material-symbols-rounded">psychology</span>
            主 Agent 规划中
            <span class="planner-stream-pulse" />
          </div>
          <div class="planner-stream-body markdown-body" v-html="renderPlannerHtml(plannerStreamingText)" />
        </div>

        <div v-if="shouldShowEvents(message)" class="agent-steps">
          <StepTimeline :events="events" />
        </div>

        <div v-else-if="shouldShowHistorySteps(message)" class="agent-steps">
          <StepTimeline :step-outcomes="historicalStepOutcomes(message)" />
        </div>

        <div class="assistant-copy" v-if="messageErrorDetail(message)">
          {{ messageErrorDetail(message) }}
        </div>

        <details v-if="hasReasoning(message)" class="reasoning-panel">
          <summary>查看规划思路</summary>
          <div class="reasoning-content">
            <section v-for="section in reasoningSections(message)" :key="section.key" class="reasoning-section">
              <h5>{{ section.title }}</h5>
              <div class="markdown-body reasoning-md" v-html="marked.parse(section.content)" />
            </section>
          </div>
        </details>

        <div
          class="assistant-body markdown-body"
          v-html="renderMd(message.contentHtml, plainMessageContent(message))"
        />

        <div
          v-if="message.id === latestAssistantId && artifacts.length"
          class="summary-list"
          style="margin-top: 14px"
        >
          <button
            v-for="artifact in artifacts"
            :key="artifact.id"
            class="file-card"
            type="button"
            @click="emit('open-artifact', artifact)"
          >
            <span class="file-icon">
              <span class="material-symbols-rounded">description</span>
            </span>
            <span>
              <strong>{{ artifact.title }}</strong>
              <p>{{ artifact.summary }}</p>
            </span>
            <span class="file-actions">
              打开文档
              <span class="material-symbols-rounded" style="font-size: 18px">chevron_right</span>
            </span>
          </button>
        </div>

        <div class="message-actions">
          <button
            class="message-action"
            type="button"
            aria-label="复制"
            :class="{ 'is-success': copiedIds.has(message.id) }"
            @click="copyMessage(message)"
          >
            <span class="material-symbols-rounded">{{ copiedIds.has(message.id) ? "check" : "content_copy" }}</span>
          </button>
          <button
            class="message-action"
            type="button"
            aria-label="点赞"
            :class="{ active: feedbackFor(message.id) === 'like' }"
            @click="toggleFeedback(message, 'like')"
          >
            <span class="material-symbols-rounded">thumb_up</span>
          </button>
          <button
            class="message-action"
            type="button"
            aria-label="点踩"
            :class="{ active: feedbackFor(message.id) === 'dislike' }"
            @click="toggleFeedback(message, 'dislike')"
          >
            <span class="material-symbols-rounded">thumb_down</span>
          </button>
          <button class="message-action" type="button" aria-label="重新生成" @click="emit('regenerate')">
            <span class="material-symbols-rounded">refresh</span>
          </button>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.planner-stream-panel {
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--outline, #e4e4e2);
  background: linear-gradient(135deg, rgba(11, 87, 208, 0.06), rgba(255, 255, 255, 0.9));
}

.planner-stream-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary-700, #0842a0);
  margin-bottom: 8px;
}

.planner-stream-label .material-symbols-rounded {
  font-size: 18px;
}

.planner-stream-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary-600, #0b57d0);
  animation: planner-pulse 1.2s ease-in-out infinite;
}

@keyframes planner-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1.1);
  }
}

.planner-stream-body {
  max-height: 280px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.55;
  color: var(--grey-800, #303030);
}

.message-action.active .material-symbols-rounded {
  font-variation-settings: "FILL" 1, "wght" 500, "GRAD" 0, "opsz" 24;
  color: var(--primary-600, #0b57d0);
}

.message-action.is-success .material-symbols-rounded {
  color: #137333;
  font-variation-settings: "FILL" 1, "wght" 500, "GRAD" 0, "opsz" 24;
}
</style>
