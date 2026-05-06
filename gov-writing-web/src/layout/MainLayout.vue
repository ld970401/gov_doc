<template>
  <div class="app-shell">
    <Sidebar />
    <div class="shell-content">
      <RouterView />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 主应用布局：左侧 Sidebar + 右侧路由内容。
 *
 * 该布局是 /chat 与 /workspace 的共同壳，负责：
 *   1. 挂载时拉取一次会话列表；
 *   2. 提供整页背景渐变（原本写在 ChatView 的 .app-shell 上，迁移到这里以覆盖所有子路由）。
 *
 * Sidebar 内部直接消费 sessionStore + router，不需要本布局透传 props/emits。
 */
import Sidebar from '@/layout/Sidebar.vue';
import { useSessionStore } from '@/stores/session';
import { ElMessage } from 'element-plus';
import { onMounted } from 'vue';

const sessionStore = useSessionStore();

onMounted(() => {
  sessionStore.loadHistory().catch((error) => {
    console.error('加载历史会话失败:', error);
    ElMessage.error('加载历史会话失败');
  });
});
</script>

<style scoped lang="scss">
.app-shell {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
  min-width: 0;
  background:
    radial-gradient(ellipse 80% 50% at 20% -10%, rgba(0, 47, 134, 0.1) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 80% 110%, rgba(50, 114, 231, 0.08) 0%, transparent 55%),
    radial-gradient(ellipse 40% 30% at 60% 50%, rgba(0, 97, 255, 0.04) 0%, transparent 50%),
    linear-gradient(160deg, #f0f4ff 0%, #f8faff 40%, #eef2fb 100%);
  background-attachment: fixed;
}

.shell-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  overflow: hidden;
  position: relative;
}
</style>
