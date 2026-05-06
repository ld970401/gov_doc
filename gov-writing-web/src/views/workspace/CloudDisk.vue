<template>
  <div class="cloud-disk">
    <div class="cloud-disk-inner">
      <!-- 顶部：标题 + 操作按钮 -->
      <div class="cd-header">
        <h1 class="cd-title">工作目录</h1>
        <div class="cd-header-actions">
          <div ref="createWrapperRef" class="create-select-wrapper" @click.stop>
            <button class="btn-create" type="button" @click.stop="toggleCreateDropdown">
              <el-icon><Plus /></el-icon>
              <span>新建</span>
              <el-icon class="chevron"><ArrowDown /></el-icon>
            </button>
            <div
              class="cd-dropdown create-dropdown floating-dropdown-panel"
              :class="{ 'is-open': isCreateDropdownOpen }"
            >
              <div
                v-for="option in createOptions"
                :key="option.id"
                class="cd-dropdown-item"
                @click.stop="handleCreate(option.id)"
              >
                <el-icon><component :is="option.icon" /></el-icon>
                <span>{{ option.label }}</span>
              </div>
            </div>
          </div>

          <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false" :on-change="handleUploadChange" multiple class="cd-upload">
            <button class="btn-upload" type="button">
              <el-icon><Upload /></el-icon>
              <span>上传</span>
            </button>
          </el-upload>
        </div>
      </div>

      <!-- 分类 Tabs -->
      <div class="cd-tabs">
        <button v-for="tab in tabs" :key="tab.id" class="cd-tab" :class="{ active: activeTab === tab.id }" type="button" @click="activeTab = tab.id">
          {{ tab.label }}
        </button>
      </div>

      <!-- 面包屑 + 筛选 -->
      <div class="cd-subbar">
        <div class="cd-breadcrumb">
          <span class="cd-breadcrumb-item">全部文件</span>
          <el-icon class="cd-breadcrumb-sep"><ArrowRight /></el-icon>
        </div>
        <button class="btn-filter" type="button" @click="handleFilter">
          <el-icon><Filter /></el-icon>
          <span>筛选</span>
        </button>
      </div>

      <!-- 文件列表 -->
      <div class="cd-table">
        <div class="cd-thead">
          <div class="cd-th col-name">名称</div>
          <div class="cd-th col-owner">所有者</div>
          <div class="cd-th col-opened">最近打开</div>
          <div class="cd-th col-action"></div>
        </div>
        <div class="cd-tbody">
          <div v-for="item in currentFiles" :key="item.id" class="cd-row" :class="{ 'menu-open': openActionMenuId === item.id }" @click="handleRowClick(item)">
            <div class="cd-td col-name">
              <span class="file-icon" :class="`icon-${item.type}`">
                <el-icon v-if="item.type === 'folder'"><FolderOpened /></el-icon>
                <el-icon v-else><Document /></el-icon>
              </span>
              <span class="file-name">{{ item.name }}</span>
            </div>
            <div class="cd-td col-owner">{{ item.owner }}</div>
            <div class="cd-td col-opened">{{ item.openedAt }}</div>
            <div class="cd-td col-action" @click.stop>
              <button class="row-action-btn" type="button" :aria-expanded="openActionMenuId === item.id" @click.stop="toggleActionMenu(item.id, $event)">···</button>
              <div
                class="cd-dropdown action-dropdown floating-dropdown-panel"
                :class="{ 'is-open': openActionMenuId === item.id }"
              >
                <div
                  v-for="action in rowActions"
                  :key="action.id"
                  class="cd-dropdown-item"
                  :class="{ danger: action.danger, disabled: isActionDisabled(action.id) }"
                  @click.stop="handleRowAction(action.id, item)"
                >
                  <el-icon><component :is="action.icon" /></el-icon>
                  <span>{{ action.label }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!currentFiles.length" class="cd-empty">暂无文件</div>
        </div>
      </div>
    </div>

    <!-- 输入框弹窗（新建文件夹 / 新建docx / 重命名） -->
    <Teleport to="body">
      <Transition name="cd-modal-fade">
        <div v-if="promptState.visible" class="cd-modal-mask" @mousedown.self="closePrompt">
          <div class="cd-modal" role="dialog" aria-modal="true">
            <div class="cd-modal-title">{{ promptState.title }}</div>
            <input ref="promptInputRef" v-model="promptState.value" type="text" class="cd-modal-input" :placeholder="promptState.placeholder" :maxlength="50" @keyup.enter="confirmPrompt" @keyup.escape="closePrompt" />
            <div class="cd-modal-footer">
              <button class="cd-modal-btn cancel" type="button" @click="closePrompt">取消</button>
              <button class="cd-modal-btn confirm" type="button" @click="confirmPrompt">确认</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown, ArrowRight, ChatDotRound, Delete, Document, Download, EditPen, Filter, FolderOpened, Plus, Rank, Upload } from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus';
import { computed, markRaw, nextTick, onMounted, onUnmounted, reactive, ref, type Component } from 'vue';

interface CloudFile {
  id: string;
  name: string;
  type: 'doc' | 'folder';
  owner: string;
  openedAt: string;
}

interface CreateOption {
  id: 'docx' | 'folder';
  label: string;
  icon: Component;
}

interface RowAction {
  id: 'move-chat' | 'move' | 'download' | 'rename' | 'delete';
  label: string;
  icon: Component;
  danger?: boolean;
  disabled?: boolean;
}

const emit = defineEmits<{
  'file-open': [file: CloudFile];
}>();

const tabs = [
  { id: 'recent', label: '最近' },
  { id: 'mine', label: '我的' },
  { id: 'ai', label: 'AI文档' },
];

const activeTab = ref<string>('recent');

const recentFiles = ref<CloudFile[]>([
  { id: '1', name: '关于开会的通知', type: 'doc', owner: '张三', openedAt: '3月23日 16:36' },
  { id: '2', name: '2025年度材料', type: 'folder', owner: '张三', openedAt: '3月22日 09:10' },
  { id: '3', name: '2025年工作计划', type: 'doc', owner: '张三', openedAt: '3月21日 14:05' },
  { id: '4', name: '党建活动总结报告', type: 'doc', owner: '张三', openedAt: '3月20日 11:30' },
]);

const myFiles = ref<CloudFile[]>([
  { id: 'm1', name: '我的工作记录', type: 'doc', owner: '我', openedAt: '3月25日 09:20' },
  { id: 'm2', name: '个人素材', type: 'folder', owner: '我', openedAt: '3月24日 18:05' },
]);

const aiFiles = ref<CloudFile[]>([
  { id: 'a1', name: 'AI生成-年度工作总结', type: 'doc', owner: 'AI', openedAt: '3月25日 14:12' },
  { id: 'a2', name: 'AI生成-政策解读', type: 'doc', owner: 'AI', openedAt: '3月24日 10:30' },
]);

const currentFiles = computed(() => {
  if (activeTab.value === 'mine') return myFiles.value;
  if (activeTab.value === 'ai') return aiFiles.value;
  return recentFiles.value;
});

const uploadRef = ref();
const createWrapperRef = ref<HTMLElement | null>(null);
const isCreateDropdownOpen = ref(false);
const openActionMenuId = ref<string | null>(null);

const promptInputRef = ref<HTMLInputElement | null>(null);
const promptState = reactive<{
  visible: boolean;
  title: string;
  placeholder: string;
  value: string;
  resolve: ((value: string | null) => void) | null;
}>({
  visible: false,
  title: '',
  placeholder: '',
  value: '',
  resolve: null,
});

const openPrompt = (opts: { title: string; placeholder?: string; initialValue?: string }): Promise<string | null> => {
  promptState.title = opts.title;
  promptState.placeholder = opts.placeholder ?? '';
  promptState.value = opts.initialValue ?? '';
  promptState.visible = true;
  nextTick(() => {
    promptInputRef.value?.focus();
    promptInputRef.value?.select();
  });
  return new Promise((resolve) => {
    promptState.resolve = resolve;
  });
};

const closePrompt = () => {
  promptState.visible = false;
  promptState.resolve?.(null);
  promptState.resolve = null;
};

const confirmPrompt = () => {
  const value = promptState.value.trim();
  if (!value) {
    ElMessage.warning('名称不能为空');
    return;
  }
  promptState.visible = false;
  promptState.resolve?.(value);
  promptState.resolve = null;
};

const createOptions: CreateOption[] = [
  { id: 'docx', label: 'docx文档', icon: markRaw(Document) },
  { id: 'folder', label: '文件夹', icon: markRaw(FolderOpened) },
];

const rowActions: RowAction[] = [
  { id: 'move-chat', label: '移至对话', icon: markRaw(ChatDotRound), disabled: true },
  { id: 'move', label: '移动', icon: markRaw(Rank), disabled: true },
  { id: 'download', label: '下载', icon: markRaw(Download) },
  { id: 'rename', label: '重命名', icon: markRaw(EditPen), disabled: true },
  { id: 'delete', label: '删除', icon: markRaw(Delete), danger: true },
];

const isActionDisabled = (actionId: RowAction['id']) =>
  actionId !== 'download' && actionId !== 'delete';

const toggleCreateDropdown = (event: Event) => {
  event.stopPropagation();
  isCreateDropdownOpen.value = !isCreateDropdownOpen.value;
  openActionMenuId.value = null;
};

const toggleActionMenu = (id: string, event?: MouseEvent) => {
  event?.stopPropagation();
  openActionMenuId.value = openActionMenuId.value === id ? null : id;
  isCreateDropdownOpen.value = false;
};

const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const formatNow = () => {
  const now = new Date();
  const m = now.getMonth() + 1;
  const d = now.getDate();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return `${m}月${d}日 ${hh}:${mm}`;
};

const handleCreate = async (id: CreateOption['id']) => {
  isCreateDropdownOpen.value = false;
  const isFolder = id === 'folder';
  const title = isFolder ? '新建文件夹' : '新建docx文档';
  const placeholder = isFolder ? '新建文件夹' : '新建docx文档';
  const name = await openPrompt({ title, placeholder });
  if (!name) return;
  const newItem: CloudFile = {
    id: genId(),
    name,
    type: isFolder ? 'folder' : 'doc',
    owner: '我',
    openedAt: formatNow(),
  };
  recentFiles.value.unshift(newItem);
  myFiles.value.unshift(newItem);
  ElMessage.success(isFolder ? '已新建文件夹' : '已新建 docx 文档');
};

const handleUploadChange = (file: UploadFile) => {
  if (file && file.name) {
    ElMessage.success(`已上传：${file.name}`);
  }
};

const handleFilter = () => {
  ElMessage.info('筛选功能开发中');
};

const handleRowClick = (item: CloudFile) => {
  emit('file-open', item);
};

const handleRowAction = async (actionId: RowAction['id'], item: CloudFile) => {
  if (isActionDisabled(actionId)) return;
  openActionMenuId.value = null;
  switch (actionId) {
    case 'move-chat':
      ElMessage.success(`已将「${item.name}」移至对话`);
      break;
    case 'move':
      ElMessage.info(`移动：${item.name}`);
      break;
    case 'download':
      ElMessage.success(`开始下载：${item.name}`);
      break;
    case 'rename': {
      const name = await openPrompt({
        title: '重命名',
        placeholder: '请输入新名称',
        initialValue: item.name,
      });
      if (name) {
        item.name = name;
        ElMessage.success('重命名成功');
      }
      break;
    }
    case 'delete':
      try {
        await ElMessageBox.confirm(`确定要删除「${item.name}」吗？`, '删除确认', {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
        });
        for (const list of [recentFiles.value, myFiles.value, aiFiles.value]) {
          const idx = list.findIndex((f) => f.id === item.id);
          if (idx > -1) list.splice(idx, 1);
        }
        ElMessage.success('删除成功');
      } catch {
        /* user cancelled */
      }
      break;
  }
};

const handleClickOutside = (event: PointerEvent) => {
  const target = event.target as Node | null;
  if (!target) return;
  const inCreate = !!createWrapperRef.value?.contains(target);
  const inActionMenu = !!(target as HTMLElement).closest('.col-action');
  if (!inCreate) isCreateDropdownOpen.value = false;
  if (!inActionMenu) openActionMenuId.value = null;
};

onMounted(() => {
  document.addEventListener('pointerdown', handleClickOutside, true);
});

onUnmounted(() => {
  document.removeEventListener('pointerdown', handleClickOutside, true);
});
</script>

<style scoped lang="scss">
.cloud-disk {
  flex: 1;
  width: 100%;
  height: 100%;
  overflow-y: auto;
  background: transparent;
}

.cloud-disk-inner {
  padding: 48px 56px 64px;
}

.cd-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.cd-title {
  font-size: 26px;
  font-weight: 700;
  color: #1f2937;
  margin: 0 10px 0 0;
  letter-spacing: -0.01em;
}

.cd-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.create-select-wrapper {
  position: relative;
}

.btn-create,
.btn-upload {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 16px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition:
    background 0.18s var(--ease-out),
    box-shadow 0.18s var(--ease-out),
    border-color 0.18s var(--ease-out),
    transform 0.18s var(--ease-out);

  .el-icon {
    font-size: 16px;

    &.chevron {
      font-size: 14px;
      margin-left: 2px;
      opacity: 0.85;
    }
  }
}

.btn-create {
  background: var(--primary-gradient, var(--primary));
  color: var(--on-primary, #fff);
  border: none;
  box-shadow: 0 4px 12px rgba(0, 47, 134, 0.22);

  &:hover {
    box-shadow: 0 4px 14px rgba(0, 47, 134, 0.32);
    transform: translateY(-1px);
  }
}

.btn-upload {
  background: #fff;
  color: #1f2937;
  border: 1px solid var(--outline-variant, #e5e7eb);

  &:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .el-icon {
    color: #4b5563;
  }
}

.cd-upload {
  :deep(.el-upload) {
    display: inline-block;
  }
}

.cd-tabs {
  display: flex;
  align-items: center;
  gap: 28px;
  border-bottom: 1px solid var(--outline-variant, #e5e7eb);
  margin-bottom: 8px;
}

.cd-tab {
  position: relative;
  padding: 10px 2px 14px;
  border: none;
  background: transparent;
  font-size: 15px;
  font-weight: 500;
  color: #6b7280;
  cursor: pointer;
  font-family: inherit;
  transition: color 0.15s ease;

  &:hover {
    color: #1f2937;
  }

  &.active {
    color: var(--primary);
    font-weight: 600;

    &::after {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      bottom: -1px;
      height: 2px;
      background: var(--primary);
      border-radius: 2px 2px 0 0;
    }
  }
}

.cd-subbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0 18px;
}

.cd-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #9ca3af;
}

.cd-breadcrumb-item {
  font-weight: 500;
}

.cd-breadcrumb-sep {
  font-size: 12px;
}

.btn-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 20px;
  font-family: inherit;
  transition: background 0.12s ease;

  &:hover {
    background: var(--surface-overlay, rgba(0, 0, 0, 0.04));
    color: #1f2937;
  }

  .el-icon {
    font-size: 14px;
  }
}

/* 统一下拉浮层：样式与 ChatInput 的 model-dropdown 一致 */
.cd-dropdown {
  background: var(--surface);
  border: 1px solid var(--outline);
  border-radius: 12px;
  box-shadow: var(--shadow-3);
  padding: 4px;
  min-width: 140px;
  z-index: var(--dropdown-z-index);
}

.cd-dropdown.floating-dropdown-panel {
  transform-origin: top right;
}

.cd-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 14px;
  color: var(--on-surface);
  cursor: pointer;
  border-radius: 8px;
  transition: background 0.12s ease;
  white-space: nowrap;

  &:hover {
    background: var(--surface-overlay);
  }

  &.disabled {
    color: #9ca3af;
    cursor: not-allowed;

    .el-icon {
      color: #9ca3af;
    }

    &:hover {
      background: transparent;
    }
  }

  &.danger {
    color: var(--error, #b3261e);

    .el-icon {
      color: var(--error, #b3261e);
    }
  }

  .el-icon {
    font-size: 16px;
    color: var(--on-surface-variant);
  }
}

.create-dropdown {
  top: calc(100% + 8px);
  left: 0;
}

.action-dropdown {
  top: calc(100% + 6px);
  right: 0;
  min-width: 140px;
}

.cd-table {
  width: 100%;
}

.cd-thead {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px 200px 100px;
  padding: 0 8px 14px;
  font-size: 13px;
  color: #9ca3af;
  font-weight: 500;
  border-bottom: 1px solid var(--outline-variant, #eef0f3);
}

.cd-tbody {
  display: flex;
  flex-direction: column;
}

.cd-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px 200px 100px;
  align-items: center;
  padding: 14px 8px;
  border-bottom: 1px solid rgba(229, 231, 235, 0.6);
  cursor: pointer;
  transition: background 0.12s ease;
  position: relative;

  &:hover {
    background: rgba(0, 47, 134, 0.04);
  }

  &:hover .row-action-btn,
  &.menu-open .row-action-btn {
    opacity: 1;
  }
}

.cd-td.col-action {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}

.cd-th.col-action {
  overflow: visible;
}

.row-action-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1.5px;
  line-height: 1;
  opacity: 0;
  transition:
    opacity 0.12s ease,
    background 0.12s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.06);
    color: #1f2937;
  }
}

.cd-td {
  font-size: 14px;
  color: #1f2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-name {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;

  .file-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #1f2937;
    font-weight: 500;
  }
}

.col-owner,
.col-opened {
  color: #4b5563;
  font-size: 13.5px;
}

.file-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;

  .el-icon {
    font-size: 18px;
  }

  &.icon-doc {
    background: rgba(0, 47, 134, 0.08);
    color: var(--primary);
  }

  &.icon-folder {
    background: rgba(245, 158, 11, 0.12);
    color: #f59e0b;
  }
}

.cd-empty {
  padding: 56px 0;
  text-align: center;
  color: #9ca3af;
  font-size: 14px;
}
</style>

<style lang="scss">
/* 输入弹窗（非 scoped，方便 Teleport 到 body 时生效） */
.cd-modal-mask {
  position: fixed;
  padding-top: 15vh;
  inset: 0;
  background: rgba(15, 23, 42, 0.32);
  display: flex;
  justify-content: center;
  z-index: 2000;
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.cd-modal {
  height: 220px;
  width: min(620px, calc(100vw - 48px));
  background: #ffffff;
  border-radius: 20px;
  padding: 30px 34px 26px;
  box-shadow:
    0 24px 60px rgba(15, 23, 42, 0.18),
    0 8px 20px rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  gap: 20px;
  font-family: inherit;
}

.cd-modal-title {
  font-size: 18px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.4;
}

.cd-modal-input {
  width: 100%;
  height: 52px;
  padding: 0 18px;
  border-radius: 12px;
  border: 1.5px solid #c7d2fe;
  font-size: 15px;
  color: #1f2937;
  background: #ffffff;
  outline: none;
  font-family: inherit;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;

  &::placeholder {
    color: #9ca3af;
  }

  &:hover {
    border-color: #93a5fd;
  }

  &:focus {
    border-color: #3b5bff;
    box-shadow: 0 0 0 3px rgba(59, 91, 255, 0.18);
  }
}

.cd-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 4px;
}

.cd-modal-btn {
  min-width: 96px;
  height: 42px;
  padding: 0 22px;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;

  &.cancel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    color: #1f2937;

    &:hover {
      background: #f9fafb;
      border-color: #d1d5db;
    }
  }

  &.confirm {
    background: var(--primary-gradient, var(--primary, #0b57d0));
    border: none;
    color: #ffffff;
    box-shadow: 0 6px 16px rgba(0, 47, 134, 0.28);

    &:hover {
      box-shadow: 0 6px 18px rgba(0, 47, 134, 0.38);
      transform: translateY(-1px);
    }

    &:active {
      transform: translateY(0);
    }
  }
}

.cd-modal-fade-enter-active,
.cd-modal-fade-leave-active {
  transition: opacity 0.18s ease;

  .cd-modal {
    transition:
      transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 0.18s ease;
  }
}

.cd-modal-fade-enter-from,
.cd-modal-fade-leave-to {
  opacity: 0;

  .cd-modal {
    transform: translateY(8px) scale(0.98);
    opacity: 0;
  }
}
</style>
