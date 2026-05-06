<template>
  <div class="linked-editor-panel-inner">
    <header class="linked-editor-head">
      <div class="linked-editor-head-row">
        <div class="linked-editor-meta">
          <h2 class="linked-doc-title" v-html="docTitleDisplay"></h2>
        </div>
        <button
          type="button"
          class="linked-editor-close"
          title="关闭"
          aria-label="关闭"
          @click="emit('close')"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </header>

    <div class="linked-editor-scroll">
      <div class="linked-editor-paper-wrap">
        <TinymceDocEditor v-model="step.content.body" compact auto-grow />
      </div>
    </div>

    <footer class="linked-editor-foot">
      <span class="linked-editor-demo-note"></span>
      <div class="linked-editor-foot-actions">
        <!-- <button type="button" class="btn-save-demo" @click="onSaveDemo">保存演示态</button> -->
        <button type="button" class="btn-close-panel" @click="emit('close')">关闭</button>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { Close, Document } from '@element-plus/icons-vue';
import { computed } from 'vue';
import TinymceDocEditor from '@/components/rich-text/TinymceDocEditor.vue';

const props = defineProps<{
  step: Step;
}>();

const emit = defineEmits<{
  close: [];
}>();

/** 标题区去掉 .docx 后缀以贴近设计稿 */
const docTitleDisplay = computed(() => {
  const raw = props.step.label || '文档';
  return raw.replace(/\.docx\s*$/i, '');
});

const hint = computed(() => {
  const c = props.step.content as Record<string, unknown> | undefined;
  if (!c) return '';
  return (c.footerHint as string) || '点击结果文件后，可在右侧编辑器继续修改正文。';
});

const onSaveDemo = () => {
  /* 演示占位：可接持久化 */
};
</script>

<style scoped lang="scss">
$le-primary: #0b57d0;
$le-primary-hover: #4096ff;
$le-bg: #ffffff;
$le-text: #262626;
$le-text-secondary: #8c8c8c;
$le-border: #e8e8e8;
$le-editor-outline: #8cc4ff;
$le-radius-card: 14px;
$le-radius-pill: 20px;

.linked-editor-panel-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: $le-bg;
}

.linked-editor-head {
  flex-shrink: 0;
  padding: 20px 24px 10px;
}

.linked-editor-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.linked-editor-brand {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #e8f0fe;
  color: #0842a0;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 10px;

  .el-icon {
    top: 1px;
  }
}

.linked-editor-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: $le-text-secondary;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.04);
    color: $le-text;
  }

  .el-icon {
    font-size: 18px;
  }
}

.linked-editor-meta {
  flex-shrink: 0;
}

.linked-doc-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 700;
  color: #000000;
  line-height: 1.35;
  letter-spacing: 0.01em;
}

.linked-doc-hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #8c8c8c;
}

.linked-editor-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0 24px 24px;
  scrollbar-width: thin;
  scrollbar-color: #d9d9d9 transparent;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-thumb {
    background: #d9d9d9;
    border-radius: 6px;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }
}

.linked-editor-paper-wrap {
  height: 100%;
}

.linked-editor-foot {
  flex-shrink: 0;
  padding: 16px 24px 20px;
  border-top: 1px solid #f0f0f0;
  background: #ffffff;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.linked-editor-demo-note {
  font-size: 12px;
  color: $le-text-secondary;
  line-height: 1.5;
  max-width: 58%;
  flex: 1;
  min-width: 200px;
}

.linked-editor-foot-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.btn-save-demo {
  height: 36px;
  padding: 0 22px;
  border-radius: $le-radius-pill;
  border: 1px solid $le-primary;
  background: #ffffff;
  font-size: 14px;
  font-weight: 500;
  color: $le-primary;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: $le-primary-hover;
    color: $le-primary-hover;
    background: #f0f7ff;
  }
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
  transition: box-shadow 0.18s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);

  &:hover {
    box-shadow: 0 4px 14px rgba(0, 47, 134, 0.4);
    transform: translateY(-1px);
  }
}
</style>
