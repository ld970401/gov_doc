import { createRouter, createWebHashHistory } from 'vue-router';
import Layout from '@/layout/Layout.vue';

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: Layout,
      children: [
        { path: '', redirect: '/chat' },
        {
          // 主布局壳：左 Sidebar + 右 RouterView，覆盖 /chat 与 /workspace
          path: '',
          component: () => import('@/layout/MainLayout.vue'),
          children: [
            {
              path: 'chat/:sessionId?',
              name: 'chat',
              component: () => import('@/views/chat/index.vue'),
            },
            {
              path: 'workspace',
              name: 'workspace',
              component: () => import('@/views/workspace/index.vue'),
            },
          ],
        },
      ],
    },
  ],
});

export default router;
