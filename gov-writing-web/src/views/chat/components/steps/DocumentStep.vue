<template>
  <div class="document-output-card">
    <div class="doc-card-header">
      <div class="doc-card-header-main">
        <div class="doc-badge">
          <span class="doc-badge-icon" aria-hidden="true">
            <el-icon><Document /></el-icon>
          </span>
          <span>{{ badgeText }}</span>
        </div>
        <!-- <h2 class="doc-card-title" v-html="step.label || defaultTitle"></h2> -->
      </div>
    </div>

    <div ref="previewPanelRef" class="doc-preview-panel">
      <div class="doc-preview-content" v-html="displayedBody"></div>
    </div>

    <div class="doc-card-footer">
      <span class="doc-footer-hint"></span>
      <button v-if="showOpenEditor" type="button" class="doc-open-editor" @click="openEditor">
        {{ openEditorText }}
        <el-icon class="doc-open-chevron"><ArrowRight /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowRight, Document } from '@element-plus/icons-vue';
import { computed, inject, nextTick, ref, watch } from 'vue';
import { parse } from '@/utils/document-parser';
import { LINKED_EDITOR_KEY } from '../../linkedEditor';

const props = withDefaults(
  defineProps<{
    step: Step;
    animated?: boolean;
    badgeText?: string;
    defaultTitle?: string;
    openEditorText?: string;
    showOpenEditor?: boolean;
  }>(),
  {
    animated: true,
    badgeText: '文档输出',
    defaultTitle: '生成文档',
    openEditorText: '在右侧编辑器打开',
    showOpenEditor: true,
  }
);

const emit = defineEmits<{
  'streaming-complete': [];
}>();

const linkedHost = inject(LINKED_EDITOR_KEY, null);
const previewPanelRef = ref<HTMLElement | null>(null);
const displayedBody = ref('');
const lastFormattedSource = ref('');

const bodyText = computed(() =>
  props.step.content && typeof props.step.content === 'object'
    ? String((props.step.content as { body?: unknown }).body ?? '')
    : ''
);
const isStreaming = computed(() => props.step.streaming === true);

const scrollPreviewToBottom = () => {
  nextTick(() => {
    const host = previewPanelRef.value;
    if (!host) return;
    host.scrollTop = host.scrollHeight;
  });
};

const formatBody = (rawText: string) => {
  if (lastFormattedSource.value === rawText) return;
  displayedBody.value = parse(rawText);
  lastFormattedSource.value = rawText;
};

watch(
  () => bodyText.value,
  (rawText) => {
    const text = rawText || '';
    if (isStreaming.value) {
      displayedBody.value = text;
      scrollPreviewToBottom();
      return;
    }
    formatBody(text);
  },
  { immediate: true }
);

watch(
  () => isStreaming.value,
  (streaming) => {
    if (streaming) return;
    formatBody(bodyText.value || '');
    emit('streaming-complete');
  },
  { immediate: true }
);

const openEditor = () => {
  if (!linkedHost) return;
  const parsedBody = parse(bodyText.value || '');
  const nextStep: Step = {
    ...props.step,
    content: {
      ...(props.step.content && typeof props.step.content === 'object'
        ? (props.step.content as Record<string, unknown>)
        : {}),
      body: parsedBody,
    },
  };
  linkedHost.open(nextStep);
};
</script>

<style scoped lang="scss">
.document-output-card {
  width: 100%;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.doc-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px 12px;
}

.doc-card-header-main {
  flex: 1;
  min-width: 0;
}

.doc-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 10px;
}

.doc-badge-icon {
  font-size: 14px;
  line-height: 1;
  display: inline-flex;
}

.doc-card-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.45;
  word-break: break-word;
}

.doc-preview-panel {
  margin: 0 16px 16px;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid #e8ecf1;
  max-height: 500px;
  overflow: auto;

  .doc-preview-content {
    white-space: pre-wrap;
    font-family: 'Times New Roman', 'FangSong', '仿宋', '仿宋_GB2312', 'STFangsong', serif;
    font-size: 16pt;
    line-height: 1.8;
    color: #1f2937;

    :deep(p) {
      margin: 0;
    }
  }
}

.doc-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px 16px;
  border-top: 1px solid #f1f5f9;
}

.doc-footer-hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  flex: 1;
  min-width: 0;
}

.doc-open-editor {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: none;
  background: none;
  font-size: 13px;
  font-weight: 600;
  color: #2563eb;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease;

  &:hover {
    color: #1d4ed8;
  }
}

.doc-open-chevron {
  font-size: 14px;
}
</style>
