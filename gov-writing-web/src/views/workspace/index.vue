<template>
  <CloudDisk @file-open="handleFileOpen" />
</template>

<script setup lang="ts">
/**
 * /workspace 路由入口：极薄包装，仅负责挂载 CloudDisk 并接收文件打开事件。
 *
 * 后续如果"打开文件"需要跳转到对话或编辑器，再在此处用 router.push 接入。
 */
import CloudDisk from './CloudDisk.vue';

const handleFileOpen = (file: { id: string; name: string; type: string }) => {
  // 占位：真实跳转/打开逻辑待产品决定。
  console.log('打开云盘文件:', file);
};
</script>
