<template>
  <div class="bottom-area">
    <div class="bottom-area-inner">
      <!-- 技能信息提示框 -->
      <div v-if="selectedSkillMeta" class="skill-info-banner">
        <div class="skill-info-content">
          <div class="skill-info-title">已选技能：{{ selectedSkillMeta.name }}</div>
          <div class="skill-info-example">例如：{{ selectedSkillMeta.example }}</div>
        </div>
        <button class="skill-info-cancel" @click="clearSkill" type="button">
          <el-icon><Close /></el-icon>
          取消技能
        </button>
      </div>

      <!-- 聊天输入卡片 -->
      <div class="chat-input-card">
        <!-- 新增：已上传文件列表展示 -->
        <div v-if="fileList.length > 0" class="uploaded-files-container">
          <div v-for="(file, index) in fileList" :key="index" class="file-item">
            <div class="file-info">
              <el-icon class="file-icon"><Document /></el-icon>
              <span class="file-name">{{ file.name }}</span>
              <span class="file-size">{{ formatFileSize(file.size) }}</span>
            </div>
            <el-icon class="remove-icon" @click="removeFile(index)"><Close /></el-icon>
          </div>
        </div>

        <div class="chat-input-row">
          <!-- 附件按钮 -->
          <div ref="attachWrapperRef" class="attach-popover-wrapper" @click.stop>
            <button class="attach-btn" @click.stop="toggleAttachPopover" title="添加附件">
              <el-icon><Plus /></el-icon>
            </button>
            <div
              class="attach-popover floating-dropdown-panel"
              :class="{ 'is-open': isAttachPopoverOpen }"
            >
              <!-- 修改：使用 el-upload 触发本地上传 -->
              <el-upload
                ref="uploadRef"
                :auto-upload="false"
                :show-file-list="false"
                :on-change="handleFileChange"
                accept=".doc,.docx,.pdf,.txt,.jpg,.png,.jpeg"
                style="display: inline-block; width: 100%"
              >
                <button class="popover-item">
                  <el-icon><Upload /></el-icon>
                  本地上传
                </button>
              </el-upload>

              <button class="popover-item" @click.stop="handleCloudSelect">
                <el-icon><MostlyCloudy /></el-icon>
                网盘选择
              </button>
            </div>
          </div>

          <!-- 输入框 -->
          <input
            ref="inputRef"
            v-model="inputText"
            type="text"
            class="chat-input-field"
            :placeholder="inputPlaceholder"
            @keyup.enter="handleSend"
            @focus="handleFocus"
          />

          <!-- 模型选择 -->
          <div ref="modelWrapperRef" class="model-select-wrapper" @click.stop>
            <button class="btn-model-select" @click.stop="toggleModelDropdown" type="button">
              <el-icon><ChatLineRound /></el-icon>
              <span class="model-label" :title="selectedModelLabel">
                {{ selectedModelLabel }}
              </span>
              <el-icon class="chevron"><ArrowDown /></el-icon>
            </button>
            <div
              class="model-dropdown floating-dropdown-panel"
              :class="{ 'is-open': isModelDropdownOpen }"
            >
              <div
                v-for="model in modelOptions"
                :key="model.key"
                class="model-option"
                :class="{ selected: selectedModel === model.key }"
                @click.stop="selectModel(model)"
                :title="model.label"
              >
                <span class="model-option-label">{{ model.label }}</span>
                <el-icon class="check-icon"><Check /></el-icon>
              </div>
            </div>
          </div>

          <!-- 发送按钮 -->
          <button class="btn-send" @click="handleSend" type="button">
            <el-icon><Promotion /></el-icon>
            发送
          </button>
        </div>
      </div>

      <!-- 技能快捷选择卡片 -->
      <div class="skill-select-card">
        <div class="claw-chips-row">
          <div
            v-for="skill in skills"
            :key="skill.id"
            class="claw-chip"
            :class="{
              active: selectedSkill === skill.id,
              disabled: skill.id !== 'retrieval' && skill.id !== 'writing',
            }"
            @click="selectSkill(skill)"
          >
            <span class="claw-icon">
              <el-icon><component :is="skill.icon" /></el-icon>
            </span>
            {{ skill.name }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { listModels, listSkills } from '@/api';
import { useUserStore } from '@/stores/user';
import {
  ArrowDown,
  ChatLineRound,
  Check,
  Close,
  Document,
  DocumentChecked,
  DocumentCopy,
  EditPen,
  MagicStick,
  MostlyCloudy,
  Plus,
  Promotion,
  Search,
  Upload,
} from '@element-plus/icons-vue';
import type { UploadUserFile } from 'element-plus';
import { computed, markRaw, onMounted, onUnmounted, ref, type Component } from 'vue';

interface Skill {
  id: string;
  name: string;
  example: string;
  icon: Component;
}

type SkillIconMap = Record<string, Component>;

interface SendData {
  text: string;
  model: string;
  claw: string | null;
  skill?: string | null;
  skillLabel?: string | null;
  files?: UploadUserFile[];
}

const emit = defineEmits<{
  send: [data: SendData];
  'skill-select': [claw: string | null];
  'prompt-click': [prompt: string];
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const attachWrapperRef = ref<HTMLElement | null>(null);
const modelWrapperRef = ref<HTMLElement | null>(null);
const inputText = ref('');
const userStore = useUserStore();
const selectedModel = ref('');
const selectedSkill = ref<string | null>(null);
const isAttachPopoverOpen = ref(false);
const isModelDropdownOpen = ref(false);

const fileList = ref<UploadUserFile[]>([]);

const modelOptions = ref<Array<{ key: string; label: string }>>([]);
const skills = ref<Skill[]>([]);

const skillIconMap: SkillIconMap = {
  retrieval: markRaw(Search),
  writing: markRaw(EditPen),
  review: markRaw(DocumentChecked),
  dedup: markRaw(DocumentCopy),
  layout: markRaw(MagicStick),
};

const selectedSkillMeta = computed(
  () => skills.value.find((s) => s.id === selectedSkill.value) || null
);
const selectedModelLabel = computed(
  () => modelOptions.value.find((m) => m.key === selectedModel.value)?.label || selectedModel.value
);

const inputPlaceholder = computed(() =>
  selectedSkillMeta.value ? `例如：${selectedSkillMeta.value.example}` : '有什么我能帮你的吗？'
);

const toggleAttachPopover = () => {
  isAttachPopoverOpen.value = !isAttachPopoverOpen.value;
  isModelDropdownOpen.value = false;
};

const loadSkillOptions = async () => {
  try {
    const items = await listSkills();
    skills.value = items.map((item) => ({
      id: item.key,
      name: item.title,
      example: item.examples ? item.examples[0] : '',
      icon: skillIconMap[item.key] || markRaw(MagicStick),
    }));
  } catch (error) {
    console.error('加载技能列表失败:', error);
  }
};

const loadModelOptions = async () => {
  try {
    const items = await listModels();
    modelOptions.value = items.map((item) => ({
      key: item.modelName,
      label: item.modelDisplayName,
    }));
  } catch (error) {
    console.error('加载模型列表失败:', error);
  }

  if (!selectedModel.value) {
    selectedModel.value = userStore.me?.defaultModel || modelOptions.value[0]?.key || 'qwen-max';
  }
};

const toggleModelDropdown = (event: Event) => {
  event.stopPropagation();
  isModelDropdownOpen.value = !isModelDropdownOpen.value;
  isAttachPopoverOpen.value = false;
};

const selectModel = (model: { key: string; label: string }) => {
  selectedModel.value = model.key;
  isModelDropdownOpen.value = false;
};

const selectSkill = (skill: Skill) => {
  if (skill.id === 'retrieval' || skill.id === 'writing') {
    if (selectedSkill.value === skill.id) {
      selectedSkill.value = null;
    } else {
      selectedSkill.value = skill.id;
    }
    emit('skill-select', selectedSkillMeta.value?.id || null);
  }
};

const clearSkill = () => {
  selectedSkill.value = null;
  emit('skill-select', null);
};

const handleSend = () => {
  if (inputText.value.trim() || fileList.value.length > 0) {
    const skillKey = selectedSkillMeta.value?.id || null;
    const skillName = selectedSkillMeta.value?.name || null;
    emit('send', {
      text: inputText.value,
      model: selectedModel.value,
      claw: skillKey,
      skill: skillKey,
      skillLabel: skillName,
      files: [...fileList.value],
    });
    inputText.value = '';
    fileList.value = [];
  }
};

// 新增：处理文件选择
const handleFileChange = (uploadFile: UploadUserFile) => {
  // 简单去重检查，可根据需要扩展
  const exists = fileList.value.some((f) => f.uid === uploadFile.uid);
  if (!exists && uploadFile.raw) {
    fileList.value.push(uploadFile);
  }
  isAttachPopoverOpen.value = false;
};

// 新增：删除文件
const removeFile = (index: number) => {
  fileList.value.splice(index, 1);
};

// 新增：格式化文件大小
const formatFileSize = (bytes?: number) => {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const handleCloudSelect = () => {
  console.log('网盘选择');
  isAttachPopoverOpen.value = false;
};

const handleFocus = () => {
  // 点击输入框时关闭所有下拉菜单
  isAttachPopoverOpen.value = false;
  isModelDropdownOpen.value = false;
};

// 暴露方法给父组件
defineExpose({
  setInputText: (text: string) => {
    inputText.value = text;
    // 聚焦到输入框
    if (inputRef.value) {
      inputRef.value.focus();
    }
  },
});

// 点击外部关闭下拉菜单
const closeDropdowns = (event: PointerEvent) => {
  const target = event.target as Node | null;
  if (!target) return;
  const inAttach = !!attachWrapperRef.value?.contains(target);
  const inModel = !!modelWrapperRef.value?.contains(target);
  if (!inAttach) {
    isAttachPopoverOpen.value = false;
  }
  if (!inModel) {
    isModelDropdownOpen.value = false;
  }
};

onMounted(() => {
  void loadSkillOptions();
  void loadModelOptions();
  // 使用 pointerdown capture 统一处理外部点击，避免 click + raf 抑制导致的闪烁。
  document.addEventListener('pointerdown', closeDropdowns, true);
});

onUnmounted(() => {
  document.removeEventListener('pointerdown', closeDropdowns, true);
});
</script>

<style scoped lang="scss">
.bottom-area {
  flex-shrink: 0;
  width: 100%;
  background: transparent;
  z-index: 1000;

  .bottom-area-inner {
    max-width: 760px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 0 auto;
    padding: 20px 0;
    position: relative;
  }
}

.skill-info-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  background: #ebf3fe;
  border: 1px solid rgba(0, 47, 134, 0.14);
  border-radius: var(--radius-xl, 16px);
  color: var(--primary);

  .skill-info-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .skill-info-title {
    font-size: 14px;
    font-weight: 600;
    line-height: 1.4;
  }

  .skill-info-example {
    color: #1f2937;
    font-size: 13px;
    line-height: 1.5;
    word-break: break-all;
  }

  .skill-info-cancel {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: transparent;
    border: none;
    color: rgba(0, 47, 134, 0.72);
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
    border-radius: 6px;
    flex-shrink: 0;
    transition: background 0.12s ease;

    &:hover {
      background: rgba(0, 47, 134, 0.08);
      color: var(--primary);
    }

    .el-icon {
      font-size: 14px;
    }
  }
}

.chat-input-card {
  width: 100%;
  border: 1px solid var(--glass-brd);
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  backdrop-filter: blur(14px) saturate(130%);
  -webkit-backdrop-filter: blur(14px) saturate(130%);
  padding: 12px 14px;
  position: relative;
  z-index: 101;
  box-shadow: var(--shadow-3);
  transition: box-shadow 0.2s var(--ease-out);

  &:focus-within {
    box-shadow: var(--shadow-4);
    border-color: rgba(0, 47, 134, 0.25);
  }
}

// 新增：文件列表容器样式
.uploaded-files-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--surface-overlay);
  border: 1px solid var(--outline);
  border-radius: 8px;
  font-size: 12px;
  color: var(--on-surface);
  max-width: 200px;

  .file-info {
    display: flex;
    align-items: center;
    gap: 6px;
    overflow: hidden;

    .file-icon {
      font-size: 14px;
      color: var(--primary);
      flex-shrink: 0;
    }

    .file-name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100px;
    }

    .file-size {
      color: var(--on-surface-variant);
      font-size: 11px;
      flex-shrink: 0;
    }
  }

  .remove-icon {
    font-size: 14px;
    color: var(--on-surface-variant);
    cursor: pointer;
    margin-left: 6px;
    flex-shrink: 0;

    &:hover {
      color: var(--error);
    }
  }
}

.chat-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.attach-popover-wrapper {
  position: relative;
  flex-shrink: 0;
}

.attach-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: var(--surface-overlay);
  color: var(--on-surface-variant);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.12s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.08);
  }
}

.attach-popover {
  bottom: calc(100% + 8px);
  left: 0;
  background: var(--surface);
  border: 1px solid var(--outline);
  border-radius: 12px;
  box-shadow: var(--shadow-3);
  padding: 4px;
  min-width: 160px;
  z-index: var(--dropdown-z-index);

  :deep(.el-upload) {
    width: 100%;
  }
}

.popover-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 14px;
  color: var(--on-surface);
  border-radius: 8px;
  text-align: left;
  transition: background 0.12s ease;

  &:hover {
    background: var(--surface-overlay);
  }

  .el-icon {
    font-size: 18px;
    color: var(--on-surface-variant);
  }
}

.chat-input-field {
  flex: 1;
  border: none;
  outline: none;
  font-family: inherit;
  font-size: 15px;
  color: var(--on-surface);
  background: transparent;
  resize: none;
  min-height: 28px;
  line-height: 1.6;

  &::placeholder {
    color: var(--on-surface-variant);
    opacity: 0.55;
  }
}

.model-select-wrapper {
  position: relative;
  flex-shrink: 0;
}

.btn-model-select {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: none;
  border: 1px solid var(--outline);
  border-radius: 20px;
  color: var(--on-surface-variant);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition:
    background 0.12s ease,
    border-color 0.12s ease;

  &:hover {
    background: var(--surface-overlay);
    border-color: rgba(0, 0, 0, 0.2);
  }

  .el-icon {
    font-size: 15px;

    &.chevron {
      font-size: 15px;
    }
  }
}

.model-label {
  display: inline-block;
  max-width: 168px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.model-dropdown {
  bottom: calc(100% + 8px);
  right: 0;
  background: var(--surface);
  border: 1px solid var(--outline);
  border-radius: 12px;
  box-shadow: var(--shadow-3);
  padding: 4px;
  min-width: 168px;
  z-index: var(--dropdown-z-index);
}

.model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  font-size: 14px;
  color: var(--on-surface);
  cursor: pointer;
  border-radius: 8px;
  transition: background 0.12s ease;

  &:hover {
    background: var(--surface-overlay);
  }

  &.selected {
    color: var(--primary);
    font-weight: 500;

    .check-icon {
      visibility: visible;
    }
  }

  .check-icon {
    font-size: 16px;
    color: var(--primary);
    visibility: hidden;
    flex-shrink: 0;
  }
}

.model-option-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.btn-send {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  background: var(--primary-gradient);
  color: var(--on-primary);
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 47, 134, 0.22);
  transition:
    box-shadow 0.18s var(--ease-out),
    transform 0.18s var(--ease-out);

  &:hover {
    box-shadow: 0 4px 14px rgba(0, 47, 134, 0.4);
    transform: translateY(-1px);
  }

  &:active {
    background: var(--primary-pressed);
  }

  .el-icon {
    font-size: 17px;
  }
}

.skill-select-card {
  width: 100%;
  border: none;
  border-radius: 20px;
  background: transparent;
  padding: 4px 16px 12px 16px;
  position: relative;
}

.claw-chips-row {
  display: flex;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.claw-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  height: 36px;
  background: rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  color: var(--on-surface);
  cursor: pointer;
  font-family: inherit;
  transition:
    background 0.12s ease,
    border-color 0.12s ease;
  backdrop-filter: blur(14px) saturate(130%);
  user-select: none;

  &:hover {
    background: rgba(0, 0, 0, 0.08);
    border-color: rgba(0, 0, 0, 0.18);
  }

  &.active {
    background: var(--primary);
    color: #ffffff;
    border-color: transparent;
  }

  &.disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
}

.claw-icon {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  svg {
    width: 14px;
    height: 14px;
    fill: #fff;
  }
}
</style>
