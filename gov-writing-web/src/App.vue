<template>
  <RouterView />
</template>

<script setup lang="ts">
import { useUserStore } from '@/stores/user';
import { onMounted } from 'vue';

const userStore = useUserStore();

onMounted(() => {
  // void userStore.fetchMe();
});
</script>
