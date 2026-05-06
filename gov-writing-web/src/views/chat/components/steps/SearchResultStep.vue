<template>
  <div class="agent-step" :class="{ open: isOpen }">
    <div class="step-header" :class="{ clickable: hasContent }" @click="toggleStep">
      <div class="step-icon search-result">
        <el-icon><Document /></el-icon>
      </div>
      <span class="step-label">
        <span class="step-prefix">检索结果</span>
      </span>
      <el-icon v-if="hasContent" class="step-chevron"><ArrowDown /></el-icon>
    </div>
    <div v-if="hasContent && isOpen" class="step-content">
      <p v-if="content.description" class="result-description">{{ content.description }}</p>
      <div class="result-list">
        <article v-for="(item, idx) in content.articles || []" :key="idx" class="result-card">
          <h5 class="article-title">{{ item.title }}</h5>
          <p class="article-desc" :title="item.description || ''">{{ item.description }}</p>
          <!-- url 由后端按需提供；当前 retrieval normalizedResult.items 不带 url，因此这里按存在性条件渲染 -->
          <a
            v-if="item.url"
            class="article-link"
            :href="item.url"
            target="_blank"
            rel="noopener noreferrer"
            >打开原文<el-icon><TopRight /></el-icon
          ></a>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown, Document, TopRight } from '@element-plus/icons-vue';
import { computed, onMounted, ref } from 'vue';

const props = defineProps<{
  step: Step;
}>();

const emit = defineEmits<{
  'streaming-complete': [];
}>();

const isOpen = ref(true);

const content = computed(() => (props.step.content || {}) as Record<string, any>);
const hasContent = computed(() => {
  return Boolean(
    content.value.title ||
    content.value.description ||
    (content.value.articles && content.value.articles.length)
  );
});

onMounted(() => {
  emit('streaming-complete');
});

const toggleStep = () => {
  if (hasContent.value) {
    isOpen.value = !isOpen.value;
  }
};
</script>

<style scoped lang="scss">
.agent-step {
  width: 100%;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
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

  &.clickable {
    cursor: pointer;
    transition: background 0.18s ease;
    &:hover {
      background: rgba(240, 244, 249, 0.72);
    }
  }
}

.step-icon {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;

  &.search-result {
    background: rgba(30, 136, 229, 0.15);
    color: #0b57d0;
  }
}

.step-label {
  flex: 1;
  .step-prefix {
    color: #64748b;
    font-weight: 500;
  }
}

.step-chevron {
  font-size: 18px;
  color: var(--on-surface-variant);
  transition: transform 0.2s ease;
}

.agent-step.open .step-chevron {
  transform: rotate(180deg);
}

.step-content {
  border-top: 1px solid rgba(227, 227, 227, 0.84);
  padding: 14px 16px 16px;
  background: rgba(255, 255, 255, 0.82);
}

.result-title {
  margin: 0 0 8px;
  font-size: 16px;
  line-height: 1.35;
  color: #1f1f1f;
  font-weight: 700;
}

.result-description {
  margin: 0 0 13px;
  font-size: 14px;
  line-height: 1.7;
  color: #555;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-card {
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  background: #fff;
  padding: 18px 20px;
}

.article-title {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.35;
  color: #1f1f1f;
}

.article-desc {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #666;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
}

.article-link {
  color: #0b57d0;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;

  .el-icon {
    top: 2px;
  }
}
</style>
