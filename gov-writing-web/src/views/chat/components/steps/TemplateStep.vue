<template>
  <div class="agent-step template-recommendation open">
    <div class="step-header">
      <div class="template-recommendation-header">
        <span class="template-recommendation-title">✦ 模板推荐</span>
      </div>
    </div>
    <div class="step-content">
      <div class="template-recommendation-content">
        <p class="template-recommendation-text">推荐优先使用"党政机关标准版"</p>
        <p class="template-recommendation-desc">该模板更适合方案文件，标题、正文、层级标题与页边距约束都已预设。你也可以继续通过上拉菜单切换到手动选模版。</p>
        <div class="template-cards">
          <div class="template-card recommended">
            <div class="template-card-title">推荐模板 · 党政机关标准版</div>
            <div class="template-card-desc">适用于通知、方案、报告等正式发文场景。标题用二号小标宋，正文仿宋_GB2312三号。</div>
          </div>
          <div class="template-card">
            <div class="template-card-title">备选模板 · 汇报材料版</div>
            <div class="template-card-desc">适用于内部汇报或专题材料，保留更强的信息层级与摘要式段落。</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';

const props = defineProps<{
  step?: Step;
}>();

const emit = defineEmits<{
  'streaming-complete': [];
}>();

// 组件挂载时触发完成事件
onMounted(() => {
  emit('streaming-complete');
});
</script>

<style scoped lang="scss">
.agent-step {
  width: 100%;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  opacity: 1;
  transform: translateY(0);
  transition:
    opacity 0.35s ease,
    transform 0.35s ease;

  &.open {
    background: #ffffff;
  }
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
  user-select: none;
  cursor: default;
}

.step-content {
  display: block;
  border-top: 1px solid #e2e8f0;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.6;
  color: #64748b;
  font-family: 'Noto Sans SC', 'Source Han Sans SC', 'PingFang SC', sans-serif;
  padding-top: 0;
  border-top: none;
}

.template-recommendation-header {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #dbeafe;
  border-radius: 15px;
  padding: 4px 10px;
}

.template-recommendation-title {
  font-size: 12px;
  font-weight: 600;
  color: #2563eb;
}

.template-recommendation-content {
  padding: 0;
}

.template-recommendation-text {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.template-recommendation-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  margin: 0 0 16px 0;
}

.template-cards {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.template-card {
  flex: 1;
  min-width: 250px;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  transition: all 0.3s ease;
}

.template-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 6px 0;
}

.template-card-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
  margin: 0;
}
</style>
