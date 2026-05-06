<template>
  <div class="linked-editor-panel-inner audit-result-panel">
    <header class="linked-editor-head">
      <div class="linked-editor-head-row">
        <div class="linked-editor-meta">
          <h2 class="linked-doc-title" v-html="docTitleDisplay"></h2>
        </div>
      </div>
    </header>

    <div class="linked-editor-scroll audit-scroll">
      <aside class="audit-issue-list">
        <article v-for="item in issueList" :key="item.id" class="issue-card">
          <h4 class="issue-title">{{ item.title }}</h4>
          <p class="issue-desc">{{ item.description }}</p>
          <div class="issue-actions">
            <button type="button" class="issue-btn accept">✓</button>
            <button type="button" class="issue-btn reject">×</button>
          </div>
        </article>
        <div v-if="issueList.length === 0" class="issue-empty">未识别到问题项</div>
      </aside>

      <div class="linked-editor-paper-wrap audit-preview-wrap">
        <TinymceDocEditor
          :preview-raw-body="bodyText"
          :preview-streaming="isStreaming"
          compact
          auto-grow
          readonly
          variant="panel"
          @streaming-complete="emit('streaming-complete')"
        />
      </div>
    </div>

    <footer class="linked-editor-foot">
      <span class="linked-editor-demo-note"></span>
      <div class="linked-editor-foot-actions">
        <button type="button" class="btn-close-panel" @click="openEditor">在右侧编辑器查看</button>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from 'vue';
import { parse } from '@/utils/document-parser';
import TinymceDocEditor from '@/components/rich-text/TinymceDocEditor.vue';
import { LINKED_EDITOR_KEY } from '../linkedEditor';

const props = withDefaults(
  defineProps<{
    step: Step;
    animated?: boolean;
  }>(),
  { animated: true }
);

const emit = defineEmits<{
  'streaming-complete': [];
}>();

const linkedHost = inject(LINKED_EDITOR_KEY, null);

const content = computed(() =>
  props.step.content && typeof props.step.content === 'object'
    ? (props.step.content as Record<string, unknown>)
    : {}
);

const bodyText = computed(() => String(content.value.body ?? ''));
const isStreaming = computed(() => props.step.streaming === true);

type IssueItem = { id: string; title: string; description: string };
const issueList = computed<IssueItem[]>(() => {
  const raw =
    (Array.isArray(content.value.issues) && content.value.issues) ||
    (Array.isArray(content.value.problems) && content.value.problems) ||
    [];
  return (raw as Array<Record<string, unknown>>).map((item, idx) => ({
    id: String(item.id || `issue-${idx}`),
    title: String(item.title || item.type || `问题${idx + 1}`),
    description: String(item.description || item.suggestion || item.message || ''),
  }));
});

const docTitleDisplay = computed(() => {
  const raw = props.step.label || '审核结果';
  return raw.replace(/\.docx\s*$/i, '');
});

const openEditor = () => {
  if (!linkedHost) return;
  const parsedBody = parse(bodyText.value || '');
  const nextStep: Step = {
    ...props.step,
    content: {
      ...content.value,
      body: parsedBody,
    },
  };
  linkedHost.open(nextStep);
};
</script>

<style scoped lang="scss">
$le-primary: #0b57d0;
$le-primary-hover: #4096ff;
$le-bg: #ffffff;
$le-text: #262626;
$le-text-secondary: #8c8c8c;

.linked-editor-panel-inner.audit-result-panel {
  height: auto;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.06);
}

.audit-scroll {
  display: grid;
  grid-template-columns: 250px 1fr;
  gap: 12px;
}

.audit-issue-list {
  max-height: 640px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.issue-card {
  border: 1px solid #dbe5f1;
  border-radius: 14px;
  background: #f8fbff;
  padding: 10px 12px;
}

.issue-title {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.issue-desc {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.55;
}

.issue-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.issue-btn {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;

  &.accept {
    background: #e8f5e9;
    color: #2e7d32;
  }
  &.reject {
    background: #ffebee;
    color: #c62828;
  }
}

.issue-empty {
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  padding: 12px;
  font-size: 13px;
  color: #64748b;
}

.audit-preview-wrap {
  min-width: 0;
}

.btn-close-panel {
  padding: 8px 20px;
  background: linear-gradient(135deg, rgba(0, 47, 134, 1), rgba(50, 114, 231, 1));
  color: #ffffff;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 47, 134, 0.22);
  transition:
    box-shadow 0.18s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);

  &:hover {
    box-shadow: 0 4px 14px rgba(0, 47, 134, 0.4);
    transform: translateY(-1px);
  }
}
</style>
