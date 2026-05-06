<template>
  <div
    class="tinymce-doc-editor"
    :class="{
      compact: compact,
      'tinymce-doc-editor--panel': variant === 'panel',
    }"
  >
    <Editor
      v-model="editorContent"
      license-key="gpl"
      :init="editorInit"
      :inline="false"
      :readonly="readonly"
    />
  </div>
</template>

<script setup lang="ts">
import Editor from '@tinymce/tinymce-vue';
import { parse } from '@/utils/document-parser';
import { computed, ref, watch } from 'vue';
import { createDocEditorInit, DOC_CONTENT_STYLE_PANEL } from './tinymce/docEditorInit';

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    compact?: boolean;
    /** 紧凑模式下根据内容自适应高度 */
    autoGrow?: boolean;
    readonly?: boolean;
    /** 右侧联动编辑器：灰底上的「纸张」样式与工具栏胶囊按钮 */
    variant?: 'default' | 'panel';
    /**
     * 若传入该 prop（含空字符串），则启用「原文 + document-parser」预览模式：
     * streaming 为 true 时编辑器展示原始文本；结束后 parse 为 HTML。
     * 此模式下内容由内部状态驱动，忽略对 modelValue 的写入（只读展示场景）。
     */
    previewRawBody?: string;
    /** 仅 preview 模式有效：流式过程中不 parse，结束后 parse 并触发 streaming-complete */
    previewStreaming?: boolean;
  }>(),
  {
    modelValue: '',
    compact: false,
    autoGrow: false,
    readonly: false,
    variant: 'default',
    previewStreaming: false,
  }
);

const emit = defineEmits<{
  'update:modelValue': [string];
  'streaming-complete': [];
}>();

const isPreviewMode = computed(() => props.previewRawBody !== undefined);

/** preview 模式：parse 后的 HTML 或流式中的原文 */
const previewBody = ref('');
const lastFormattedSource = ref('');

const formatPreviewBody = (rawText: string) => {
  if (lastFormattedSource.value === rawText) return;
  previewBody.value = parse(rawText || '');
  lastFormattedSource.value = rawText || '';
};

watch(
  () => props.previewRawBody,
  (body) => {
    if (!isPreviewMode.value) return;
    const text = body ?? '';
    if (props.previewStreaming === true) {
      previewBody.value = text;
      return;
    }
    formatPreviewBody(text);
  },
  { immediate: true }
);

watch(
  () => props.previewStreaming,
  (streaming) => {
    if (!isPreviewMode.value) return;
    if (streaming === true) return;
    formatPreviewBody(props.previewRawBody ?? '');
    emit('streaming-complete');
  },
  { immediate: true }
);

const editorContent = computed({
  get: () => (isPreviewMode.value ? previewBody.value : props.modelValue),
  set: (v: string) => {
    if (isPreviewMode.value) return;
    emit('update:modelValue', v);
  },
});

const editorInit = computed(() => {
  if (props.variant === 'panel') {
    return createDocEditorInit({
      content_style: DOC_CONTENT_STYLE_PANEL,
      min_height: 380,
      autoresize_min_height: 380,
      autoresize_bottom_margin: 24,
      statusbar: false,
      resize: true,
      fontsize_formats: '12pt 14pt 三号=16pt 18pt 20pt',
    });
  }
  return createDocEditorInit(
    props.compact
      ? props.autoGrow
        ? {
            min_height: 260,
            autoresize_min_height: 260,
            autoresize_bottom_margin: 24,
            plugins: 'lists link',
            resize: false,
          }
        : {
            min_height: 260,
            height: 680,
            plugins: 'lists link',
            resize: false,
          }
      : {
          min_height: 420,
          autoresize_min_height: 420,
        }
  );
});
</script>

<style scoped lang="scss">
.tinymce-doc-editor {
  width: 100%;
  height: 100%;

  &:not(.tinymce-doc-editor--panel) :deep(.tox-tinymce) {
    border-radius: 8px;
    border-color: #e2e8f0 !important;
  }

  &.compact :deep(.tox-tinymce) {
    border-radius: 8px;
  }

  &.tinymce-doc-editor--panel {
    width: 100%;
  }

  :deep(.tox-tinymce) {
    min-height: 500px;
    height: 100% !important;
    .tox-edit-area::before {
      display: none;
    }

    .tox-statusbar {
      display: none;
    }
  }
}
</style>
