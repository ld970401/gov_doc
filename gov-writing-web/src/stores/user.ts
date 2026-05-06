import { getMe, type AgentloopUser } from '@/api/account';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export const useUserStore = defineStore('user', () => {
  const me = ref<AgentloopUser | null>(null);
  const loading = ref(false);

  const displayName = computed(() => me.value?.name || '用户');
  const avatarChar = computed(() => {
    const n = displayName.value.trim();
    return n ? n.slice(0, 1) : '用';
  });
  const defaultModelLabel = computed(() => {
    const m = me.value?.defaultModel;
    const list = me.value?.authModels || [];
    const hit = list.find((x) => x.modelName === m);
    return hit?.modelDisplayName || list[0]?.modelDisplayName || m || '—';
  });

  async function fetchMe() {
    loading.value = true;
    try {
      me.value = await getMe();
    } finally {
      loading.value = false;
    }
  }

  return {
    me,
    loading,
    displayName,
    avatarChar,
    defaultModelLabel,
    fetchMe,
  };
});
