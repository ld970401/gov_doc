<script setup lang="ts">
import { ref, computed } from 'vue';

interface Option {
  label: string;
  desc?: string;
  count?: number;
  isAll?: boolean;
}

// --- Props and Emits ---
const props = defineProps<{
  // 控制组件显示/隐藏
  modelValue: boolean;
  // 选项数据
  options: Option[];
  // 初始选中的值
  initialSelected: Option | null;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  'confirm': [option: Option];
}>();

// --- 响应式数据 ---
// 内部维护一个临时的选中项，点击确认时才真正提交
const tempSelectedOption = ref<Option>(props.initialSelected || props.options[0]);

// --- 计算属性 ---
// 格式化数字，添加千分位分隔符
const formatNumber = (num: number): string => {
  if (typeof num !== 'number' || num === 0) return '';
  return num.toLocaleString('en-US');
};

// --- 方法 ---
// 选择一个选项
const selectOption = (option: Option) => {
  tempSelectedOption.value = option;
};

// 判断是否为当前选中项
const isSelected = (option: Option): boolean => {
  return tempSelectedOption.value && tempSelectedOption.value.label === option.label;
};

// 关闭弹窗
const close = () => {
  emit('update:modelValue', false);
};

// 处理取消事件
const handleCancel = () => {
  // 恢复为初始状态
  tempSelectedOption.value = props.initialSelected || props.options[0];
  close();
};

// 处理确认事件
const handleConfirm = () => {
  emit('confirm', tempSelectedOption.value);
  close();
};
</script>

<template>
  <Transition name="dropdown">
    <div v-show="modelValue" class="dropdown-container floating-dropdown-panel" :class="{ 'is-open': modelValue }">
      <!-- 标题栏 -->
      <header class="popup-header">
        <h4>选择名单库</h4>
      </header>

      <div class="popup-divider"></div>

      <!-- 列表区域 -->
      <ul class="popup-list">
        <li
          v-for="option in options"
          :key="option.label"
          class="list-item"
          :class="{ selected: isSelected(option) }"
          @click="selectOption(option)"
        >
          <div class="option-content">
            <span class="option-label" :class="{ 'is-all': option.isAll }">{{ option.label }}</span>
            <span v-if="option.desc" class="option-desc">{{ option.desc }}</span>
          </div>
          <div class="option-right">
            <span v-if="!option.isAll" class="option-count"
              >{{ formatNumber(option.count) }} 条</span
            >
            <!-- 选中状态的对勾 -->
            <svg
              v-if="isSelected(option)"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              class="check-icon"
            >
              <path
                fill-rule="evenodd"
                d="M19.916 4.626a.75.75 0 0 1 .208 1.04l-9 13.5a.75.75 0 0 1-1.154.114l-6-6a.75.75 0 0 1 1.06-1.06l5.353 5.353 8.493-12.74a.75.75 0 0 1 1.04-.207Z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
        </li>
      </ul>

      <div class="popup-divider"></div>

      <!-- 底部操作栏 -->
      <footer class="popup-footer">
        <button class="btn btn-cancel" @click="handleCancel">取消</button>
        <button class="btn btn-confirm" @click="handleConfirm">确认</button>
      </footer>
    </div>
  </Transition>
</template>

<style scoped>
/* --- 下拉容器 (绝对定位) --- */
.dropdown-container {
  top: calc(100% + 8px);
  left: 0;
  width: 220px; /* 缩小整体宽度至 220px */
  background: white;
  border-radius: 8px;
  box-shadow:
    0 10px 25px -5px rgba(0, 0, 0, 0.1),
    0 8px 10px -6px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: var(--dropdown-z-index);
  border: 1px solid #e5e7eb;
  transform-origin: top;
}

/* 保留微动画，仅补充可见性，不再用 scaleY=0 避免文本重绘闪烁 */
.dropdown-enter-active,
.dropdown-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.98);
}

/* --- 标题 --- */
.popup-header {
  padding: 10px 16px;
  text-align: center;
}
.popup-header h4 {
  margin: 0;
  font-size: 14px; /* 缩小标题文字 */
  font-weight: 600;
  color: #374151;
}

/* --- 分割线 --- */
.popup-divider {
  height: 1px;
  background-color: #f3f4f6;
  margin: 0 12px;
}

/* --- 列表 --- */
.popup-list {
  list-style: none;
  padding: 4px 0;
  margin: 0;
  max-height: 240px;
  overflow-y: auto;
}

.list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px; /* 缩小间距 */
  cursor: pointer;
  transition: background-color 0.2s ease;
}
.list-item:hover {
  background-color: #f9fafb;
}
.list-item.selected {
  background-color: #eff6ff;
}

.option-content {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.option-label {
  font-size: 13px; /* 缩小标签文字 */
  font-weight: 500;
  color: #111827;
}
.option-label.is-all {
  font-weight: 600;
}

.option-desc {
  font-size: 11px; /* 缩小描述文字 */
  color: #9ca3af;
}

.option-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.option-count {
  font-size: 12px; /* 缩小数量文字 */
  color: #6b7280;
}

.check-icon {
  width: 16px; /* 缩小图标 */
  height: 16px;
  color: #2563eb;
}

/* --- 底部 --- */
.popup-footer {
  display: flex;
  justify-content: flex-end; /* 按钮靠右 */
  gap: 8px;
  padding: 10px 12px;
  background-color: #f9fafb;
}

.btn {
  width: 50px; /* 固定宽度 50px */
  height: 28px; /* 固定高度 28px */
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  font-size: 12px; /* 按钮文字缩小 */
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s ease;
  padding: 0; /* 清除默认 padding */
}

.btn-cancel {
  background: white;
  color: #374151;
  border-color: #d1d5db;
}
.btn-cancel:hover {
  background-color: #f9fafb;
}

.btn-confirm {
  background: #1e3a8a;
  color: white;
}
.btn-confirm:hover {
  background: #1c357a;
}
</style>
