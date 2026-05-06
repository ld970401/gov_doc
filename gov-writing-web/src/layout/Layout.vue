<script setup lang="ts">
import { Bell, Setting, User } from '@element-plus/icons-vue';
import { computed } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
// 暂时注释掉navigation store，因为我们需要创建对应的ts文件
// import { useNavigationStore } from '../stores/navigation';

const route = useRoute();
// 暂时移除navigation store的使用
// const navigationStore = useNavigationStore();

const navItems = [
  // { label: '警务飞度', path: '/police-latitude' },
  { label: '警务助手', path: '/chat' },
  { label: '接警助手', path: '/alarm-assistant' },
  { label: '警务分析', path: '/police-analytics' },
  { label: '警情预警', path: '/alert-warning' },
];

const currentPath = computed(() => route.path);

const isActive = (targetPath: string) =>
  currentPath.value === targetPath || currentPath.value.startsWith(`${targetPath}/`);

// 暂时注释掉watch，因为我们移除了navigation store的使用
// watch(
//   () => route.fullPath,
//   () => {
//     navigationStore.setVisitedPath(route.path);
//   },
//   { immediate: true },
// );
</script>

<template>
  <div class="layout">
    <main class="layout-content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
/* ─── Layout ────────────────────────────────────────────── */
.layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.layout-content {
  flex: 1;
  overflow: auto;
  background: transparent;
}
</style>
