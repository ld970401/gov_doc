<template>
  <div class="agent-step" :class="{ open: isOpen }">
    <div class="step-header" :class="{ clickable: hasContent }" @click="toggleStep">
      <div class="step-icon plan">
        <el-icon><Memo /></el-icon>
      </div>
      <span class="step-label">制定计划</span>
      <el-icon v-if="hasContent" class="step-chevron"><ArrowDown /></el-icon>
    </div>

    <div v-if="hasContent && isOpen" class="step-content">
      <!-- <p v-if="summary" class="plan-summary">{{ summary }}</p> -->
      <ol v-if="planSteps.length" class="plan-list">
        <li v-for="(item, idx) in planSteps" :key="item.index ?? idx">
          <span class="plan-list-title">{{
            normalizePlanDisplayTitle(item.displayTitle) ||
            item.title ||
            `步骤 ${item.index ?? idx + 1}`
          }}</span>
          <span v-if="item.skillName" class="plan-list-skill">[{{ item.skillName }}]</span>
        </li>
      </ol>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 规划阶段（a2a_planning）的展示卡。
 *
 * step.content 由 reducer 在 content_block_stop(payload.tool=a2a_planning) 时一次性写入：
 *   {
 *     summary: string;          // 规划摘要文案
 *     steps:   PlanStep[];      // 后续要执行的步骤列表
 *   }
 *
 * 流式期间 step.content 为 null，仅显示 header 表示「正在规划中」。
 */
import { ArrowDown, Memo } from '@element-plus/icons-vue';
import { computed, onMounted, ref, watch } from 'vue';
import type { PlanStep, ToolStopPayload } from '@/api/chat';

const props = withDefaults(
  defineProps<{
    step: Step;
    animated?: boolean;
  }>(),
  { animated: true }
);

const emit = defineEmits<{
  'streaming-complete': [];
}>();

const isOpen = ref(true);
const normalizePlanDisplayTitle = (value?: string | null) => {
  if (!value) return '';
  const text = String(value).trim();
  return text.startsWith('请') ? text.slice(1).trim() : text;
};

const planContent = computed(() => {
  const raw = props.step.content;
  if (!raw || typeof raw !== 'object') return { summary: '', steps: [] as PlanStep[] };
  // 兼容两种来源：
  // 1) 直接是 plan 对象：{ summary, steps }
  // 2) 完整 stop payload：{ displayText, steps, plan: { summary, steps } }
  const obj = raw as { summary?: string; steps?: PlanStep[] } | ToolStopPayload;
  const payloadPlan = 'plan' in obj && obj.plan && typeof obj.plan === 'object' ? obj.plan : null;
  const summary =
    (payloadPlan?.summary as string) ||
    ('displayText' in obj && typeof obj.displayText === 'string' ? obj.displayText : '') ||
    (typeof (obj as { summary?: string }).summary === 'string'
      ? (obj as { summary?: string }).summary!
      : '');
  const steps = Array.isArray(payloadPlan?.steps)
    ? (payloadPlan!.steps as PlanStep[])
    : Array.isArray((obj as { steps?: PlanStep[] }).steps)
      ? ((obj as { steps?: PlanStep[] }).steps as PlanStep[])
      : [];
  return {
    summary,
    steps,
  };
});

const summary = computed(() => planContent.value.summary);
const planSteps = computed(() => planContent.value.steps);
const hasContent = computed(() => Boolean(summary.value || planSteps.value.length));

const toggleStep = () => {
  if (hasContent.value) {
    isOpen.value = !isOpen.value;
  }
};

onMounted(() => {
  if (props.step.streaming === false) emit('streaming-complete');
});

watch(
  () => props.step.streaming,
  (streaming) => {
    if (streaming === false) emit('streaming-complete');
  }
);
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

  &.plan {
    background: rgba(253, 230, 138, 0.25);
    color: #ca8a04;
  }
}

.step-label {
  flex: 1;
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
}

.step-chevron {
  font-size: 18px;
  color: var(--on-surface-variant);
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.agent-step.open .step-chevron {
  transform: rotate(180deg);
}

.step-content {
  border-top: 1px solid rgba(227, 227, 227, 0.84);
  padding: 14px 16px 16px;
  background: rgba(255, 255, 255, 0.82);
  font-size: 13px;
  line-height: 1.7;
  color: var(--grey-800);
}

.plan-summary {
  margin: 0 0 12px;
  color: var(--grey-700);
}

.plan-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;

  li {
    color: var(--grey-900);
  }
}

.plan-list-skill {
  margin-left: 6px;
  font-size: 12px;
  color: var(--grey-500);
}
</style>
