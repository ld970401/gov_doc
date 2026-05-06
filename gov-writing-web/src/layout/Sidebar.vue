<template>
  <aside ref="sidebarRootRef" class="sidebar">
    <div class="sidebar-brand">
      <span class="brand-name">智慧公文智能体</span>
    </div>

    <div class="sidebar-top-actions">
      <button class="btn-new-chat" @click="handleNewChat">
        <el-icon>
          <EditPen />
        </el-icon>
        新对话
      </button>
      <button
        class="btn-cloud-disk"
        :class="{ active: isWorkspaceActive }"
        @click="handleCloudDisk"
      >
        <el-icon>
          <Cloudy />
        </el-icon>
        云盘
      </button>
    </div>

    <nav class="sidebar-nav">
      <div class="nav-section-header">
        <span class="nav-section-title">历史对话</span>
      </div>
      <div v-if="sessionStore.loading" class="nav-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
      <template v-else>
        <div
          v-for="item in sessionStore.sessions"
          :key="item.id"
          class="nav-sub-item"
          :class="{ 'menu-open': openMenuId === item.id, active: sidebarActiveSessionId === item.id }"
          @click="handleSelectSession(item.id)"
        >
          <el-icon class="history-icon"><ChatDotRound /></el-icon>
          <div class="history-content">
            <span class="history-title">{{ item.title }}</span>
          </div>
          <div class="nav-actions">
            <svg
              v-if="item.pinned"
              class="history-pin"
              viewBox="0 0 1024 1024"
              xmlns="http://www.w3.org/2000/svg"
              width="26"
              height="26"
            >
              <path
                d="M595.694933 211.080533a25.6 25.6 0 0 0-43.690666 18.158934l0.2048 72.669866a42.666667 42.666667 0 0 1-12.4928 30.3104l-30.8224 30.788267a42.666667 42.666667 0 0 1-29.5936 12.4928l-148.548267 1.9456c-31.675733 0.4096-47.274667 38.775467-24.849067 61.201067l116.462934 116.462933-152.507734 173.397333a18.193067 18.193067 0 0 0 25.668267 25.634134l173.3632-152.541867 116.462933 116.462933c22.391467 22.4256 60.757333 6.826667 61.166934-24.849066l1.9456-148.548267a42.666667 42.666667 0 0 1 12.4928-29.5936l30.788266-30.8224a42.666667 42.666667 0 0 1 30.3104-12.4928l72.669867 0.238933a25.6 25.6 0 0 0 18.193067-43.690666l-217.224534-217.224534z m7.714134 90.658134l-0.034134-10.581334 129.4336 129.4336h-10.581333a93.866667 93.866667 0 0 0-66.6624 27.477334l-30.8224 30.788266a93.866667 93.866667 0 0 0-27.477333 65.160534l-1.467734 112.128-227.9424-227.976534 112.093867-1.467733a93.866667 93.866667 0 0 0 65.160533-27.477333l30.788267-30.8224a93.866667 93.866667 0 0 0 27.511467-66.6624z"
              ></path>
            </svg>
            <button class="nav-sub-item-more" @click.stop="toggleMenu(item.id, $event)">···</button>
          </div>
          <div
            class="nav-more-dropdown floating-dropdown-panel"
            :class="{ 'is-open': openMenuId === item.id }"
          >
            <button @click.stop="handleRename(item)">重命名</button>
            <button @click.stop="handlePin(item)">
              {{ item.pinned ? '取消置顶' : '置顶' }}
            </button>
            <button class="danger" @click.stop="handleDelete(item)">删除</button>
          </div>
        </div>
      </template>
    </nav>

    <div class="sidebar-footer">
      <button class="btn-switch-version" @click="handleSwitchVersion">
        <el-icon><Switch /></el-icon>
        <span>切换至旧版本</span>
      </button>
      <div class="user-info">
        <div class="user-avatar">{{ userStore.avatarChar }}</div>
        <div class="user-meta">
          <div class="user-name">{{ userStore.displayName }}</div>
          <div class="user-desc">常用模型 {{ userStore.defaultModelLabel }}</div>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="renameDialogVisible"
      title="重命名对话"
      width="400px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-input v-model="renameTitle" placeholder="请输入新名称" maxlength="50" show-word-limit />
      <template #footer>
        <el-button type="default" @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmRename" :loading="renameLoading">确定</el-button>
      </template>
    </el-dialog>
  </aside>
</template>

<script setup lang="ts">
/**
 * 公共布局左侧 Sidebar。
 *
 * 不再持有任何会话列表/当前会话状态：
 *   - 会话列表来源：useSessionStore().sessions（mount 时由 MainLayout 触发 loadHistory）；
 *   - 当前会话来源：route.params.sessionId（URL 是唯一真理源）；
 *   - 所有跳转通过 router.push({ name, params }) 完成（hash 模式下走 name 比 path 安全）。
 */
import { useSessionStore } from '@/stores/session';
import { useUserStore } from '@/stores/user';
import { ChatDotRound, Cloudy, EditPen, Loading, Paperclip, Switch } from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const userStore = useUserStore();
const sessionStore = useSessionStore();
const route = useRoute();
const router = useRouter();

const openMenuId = ref<string | null>(null);
const sidebarRootRef = ref<HTMLElement | null>(null);

const renameDialogVisible = ref(false);
const renameTitle = ref('');
const renameItem = ref<ChatSession | null>(null);
const renameLoading = ref(false);

/** 当前会话来自 URL，避免 Sidebar 与 ChatView 出现状态漂移。 */
const currentSessionId = computed(() => {
  const raw = route.params.sessionId;
  return typeof raw === 'string' ? raw : '';
});

/** 高亮项：优先路由 id；在 /chat 无 id 的新会话上，用 store 中的 scratch 真实会话 id。 */
const sidebarActiveSessionId = computed(() => {
  if (currentSessionId.value) return currentSessionId.value;
  return sessionStore.scratchActiveSessionId || '';
});

const isWorkspaceActive = computed(() => route.name === 'workspace');

const handleNewChat = () => {
  // 始终触发一次重置信号 —— 即便已经在 /chat（URL 不变），ChatView 也能据此清掉
  // 仍然挂在内存里的临时会话（messages / activeStream / activeRealSessionId）。
  sessionStore.requestReset();
  // 仅当不在 /chat 欢迎页（带了 sessionId 或在别的路由）时才需要 push，避免 NavigationDuplicated 警告。
  if (route.name !== 'chat' || currentSessionId.value !== '') {
    router.push({ name: 'chat' });
  }
};

const handleCloudDisk = () => {
  router.push({ name: 'workspace' });
};

const handleSwitchVersion = () => {
  // 占位：旧版本切换暂时由产品定义。
  ElMessage.info('切换旧版本功能待接入');
};

const handleSelectSession = (sessionId: string) => {
  openMenuId.value = null;
  if (sessionId === sidebarActiveSessionId.value && route.name === 'chat') return;
  router.push({ name: 'chat', params: { sessionId } });
};

const toggleMenu = (id: string, event?: MouseEvent) => {
  if (event) event.stopPropagation();
  openMenuId.value = openMenuId.value === id ? null : id;
};

const handleRename = (item: ChatSession) => {
  renameItem.value = item;
  renameTitle.value = item.title;
  renameDialogVisible.value = true;
  openMenuId.value = null;
};

const confirmRename = async () => {
  if (!renameTitle.value.trim()) {
    ElMessage.warning('请输入对话名称');
    return;
  }
  if (!renameItem.value) return;
  renameLoading.value = true;
  try {
    await sessionStore.renameSession(renameItem.value.id, renameTitle.value.trim());
    renameDialogVisible.value = false;
    ElMessage.success('重命名成功');
  } catch (error) {
    console.error('重命名失败:', error);
    ElMessage.error('重命名失败');
  } finally {
    renameLoading.value = false;
  }
};

const handlePin = async (item: ChatSession) => {
  try {
    const next = await sessionStore.togglePin(item.id);
    ElMessage.success(next ? '已置顶' : '已取消置顶');
  } catch (error) {
    console.error('置顶操作失败:', error);
    ElMessage.error('操作失败');
  }
  openMenuId.value = null;
};

const handleDelete = async (item: ChatSession) => {
  try {
    await ElMessageBox.confirm('确定要删除这个对话吗？', '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    });
    await sessionStore.removeSession(item.id);
    // 删除的若是当前会话，回到 /chat 欢迎页；否则保持当前路由不变。
    if (item.id === currentSessionId.value) {
      router.replace({ name: 'chat' });
    }
    ElMessage.success('删除成功');
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error);
      ElMessage.error('删除失败');
    }
  }
  openMenuId.value = null;
};

/** 点击外部关闭"更多"菜单。pointerdown + capture 比 click 更稳，不会与按钮 click 冲突。 */
const handleClickOutside = (event: PointerEvent) => {
  const root = sidebarRootRef.value;
  const target = event.target as Node | null;
  if (!root || !target) return;
  if (!root.contains(target)) openMenuId.value = null;
};

onMounted(() => {
  document.addEventListener('pointerdown', handleClickOutside, true);
});

onUnmounted(() => {
  document.removeEventListener('pointerdown', handleClickOutside, true);
});

// 路由切换时关闭打开的菜单与重命名弹窗，避免跨页残留。
// Sidebar 所在的 MainLayout 不会因 /chat ↔ /workspace 切换而卸载，
// 因此用 watch(route.fullPath) 而非 onBeforeRouteLeave。
watch(
  () => route.fullPath,
  () => {
    openMenuId.value = null;
    renameDialogVisible.value = false;
  }
);
</script>

<style scoped lang="scss">
.sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(16px);
  border-right: 1px solid rgba(227, 227, 227, 0.85);
  z-index: 10;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  height: 64px;
  flex-shrink: 0;
}

.brand-name {
  font-family: 'Space Grotesk', 'Noto Sans SC', sans-serif;
  font-size: 19px;
  font-weight: 700;
  color: #1f2937;
  letter-spacing: -0.01em;
}

.sidebar-top-actions {
  padding: 4px 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn-new-chat,
.btn-cloud-disk {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 42px;
  border-radius: 24px;
  font-size: 14px;
  cursor: pointer;
  width: 100%;
  font-family: inherit;
  transition:
    box-shadow 0.18s var(--ease-out),
    transform 0.18s var(--ease-out),
    background 0.18s var(--ease-out);

  .el-icon {
    font-size: 18px;
  }
}

.btn-new-chat {
  background: var(--primary-gradient);
  color: var(--on-primary);
  border: none;
  box-shadow: 0 4px 12px rgba(0, 47, 134, 0.24);

  &:hover {
    box-shadow: 0 4px 12px rgba(0, 47, 134, 0.3);
    transform: translateY(-1px);
  }

  &:active {
    background: var(--primary-pressed);
  }
}

.btn-cloud-disk {
  background: #fff;
  color: #1f2937;
  border: 1px solid var(--outline-variant, #e5e7eb);

  &:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  &:active {
    background: #f3f4f6;
  }

  &.active {
    background: rgba(0, 47, 134, 0.08);
    color: var(--primary);
    border-color: var(--primary-border, rgba(0, 47, 134, 0.2));

    .el-icon {
      color: var(--primary);
    }
  }

  .el-icon {
    color: var(--primary);
  }
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.nav-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px 6px;
}

.nav-section-title {
  font-size: 13px;
  font-weight: 500;
  color: #9ca3af;
  letter-spacing: 0.2px;
}

.nav-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 20px;
  color: var(--on-surface-variant);
  font-size: 13px;
}

.nav-sub-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 10px;
  margin: 2px 8px;
  color: var(--on-surface);
  font-size: 14px;
  font-weight: 400;
  transition: background 0.12s ease;
  position: relative;

  &:hover {
    background: var(--surface-overlay, rgba(0, 0, 0, 0.04));
  }

  &.active {
    background: rgba(0, 47, 134, 0.08);
    color: var(--primary);

    .history-icon {
      color: var(--primary);
    }
  }
}

.history-icon {
  font-size: 18px;
  color: #6b7280;
  flex-shrink: 0;
}

.history-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.history-title {
  font-size: 14px;
  font-weight: 500;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-subtitle {
  font-size: 12px;
  color: #9ca3af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-pin {
  color: #d97706;
  position: absolute;
  top: -2px !important;
  inset: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 1;
  transition: opacity 0.12s ease;
}

.nav-actions {
  margin-left: auto;
  width: 22px;
  height: 22px;
  position: relative;
  flex-shrink: 0;
}

.nav-sub-item-more {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 22px;
  height: 22px;
  border: none;
  background: none;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--on-surface-variant);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
  flex-shrink: 0;
  transition:
    opacity 0.12s,
    background 0.12s;

  &:hover {
    background: rgba(0, 0, 0, 0.06);
  }
}

.nav-sub-item:hover .nav-sub-item-more,
.nav-sub-item.menu-open .nav-sub-item-more {
  opacity: 1;
}

.nav-sub-item:hover .history-pin,
.nav-sub-item.menu-open .history-pin {
  opacity: 0;
}

.nav-more-dropdown {
  right: 4px;
  top: 32px;
  z-index: var(--dropdown-z-index);
  background: var(--surface);
  border: 1px solid var(--outline-variant);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  min-width: 100px;
  overflow: hidden;
}

.nav-more-dropdown.floating-dropdown-panel {
  transform-origin: top right;
}

.nav-more-dropdown button {
  display: block;
  width: 100%;
  padding: 8px 14px;
  background: none;
  border: none;
  text-align: left;
  font-size: 13px;
  color: var(--on-surface);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;

  &:hover {
    background: var(--surface-variant);
  }

  &.danger {
    color: var(--error, #b3261e);
  }
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 12px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-top: 1px solid var(--outline-variant, #e5e7eb);
  background: transparent;
}

.btn-switch-version {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  border-radius: 24px;
  background: #fff;
  color: #4b5563;
  border: 1px solid var(--outline-variant, #e5e7eb);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  width: 100%;
  font-family: inherit;
  transition:
    background 0.18s var(--ease-out),
    border-color 0.18s var(--ease-out);

  &:hover {
    background: #f9fafb;
    border-color: #d1d5db;
    color: #1f2937;
  }

  .el-icon {
    font-size: 16px;
    color: #6b7280;
  }
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--primary-gradient, var(--primary));
  color: var(--on-primary, #fff);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
  font-family: 'Noto Sans SC', sans-serif;
}

.user-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: hidden;
}

.user-name {
  font-size: 14px;
  color: #1f2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-desc {
  font-size: 12px;
  color: #9ca3af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.el-icon {
  font-size: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}
</style>
