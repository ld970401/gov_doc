<template>
  <div class="agent-steps">
    <div
      v-for="item in renderedSteps"
      :key="item._renderKey"
      class="step-row"
      :class="{ 'step-animate': animated !== false }"
    >
      <component
        :is="stepComponents[item.step.type]"
        :step="item.step"
        :animated="animated !== false"
        @streaming-complete="onStreamingComplete(item._renderKey)"
      />
    </div>
    <div v-if="showThinkingHint" class="organizing-hint">
      正在思考中
      <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { stepComponents } from './steps/index';

const props = defineProps<{
  steps: Step[];
  animated?: boolean;
  streaming?: boolean;
}>();

const emit = defineEmits<{
  'step-rendered': [payload: { stepKey: string; phase: 'revealed' }];
  'steps-complete': [payload: { phase: 'all_completed' }];
}>();

const renderedCount = ref(0);
const renderKeys = ref<string[]>([]);
const completedKeys = ref<Set<string>>(new Set());
const hasEmittedComplete = ref(false);
const waitingNext = ref(false);
let lastStepsLength = 0;
let revealNextTimer: number | null = null;

const clearRevealTimer = () => {
  if (revealNextTimer !== null) {
    clearTimeout(revealNextTimer);
    revealNextTimer = null;
  }
  waitingNext.value = false;
};

/** 当前步骤 streaming-complete 后，间隔 600ms 再展示下一步 */
const scheduleRevealNext = () => {
  clearRevealTimer();
  if (renderedCount.value >= props.steps.length) return;
  waitingNext.value = true;
  revealNextTimer = window.setTimeout(() => {
    revealNextTimer = null;
    waitingNext.value = false;
    if (renderedCount.value < props.steps.length) {
      renderedCount.value++;
      emit('step-rendered', {
        stepKey: renderKeys.value[renderedCount.value - 1] || '',
        phase: 'revealed',
      });
      // 写作阶段会一次性 append [common, document] 两个 step。
      // common 通常是进行中状态，如果严格等待其 streaming-complete，
      // document 会被阻塞到 stop 才展示，导致“文档输出不显示”。
      // 这里对“common 后面已存在待展示 step”做一次自动推进。
      const justRevealed = props.steps[Math.max(0, renderedCount.value - 1)];
      const hasPending = renderedCount.value < props.steps.length;
      if (hasPending && justRevealed?.type === 'common') {
        scheduleRevealNext();
      }
    }
  }, 600);
};

const ensureKeys = (len: number) => {
  while (renderKeys.value.length < len) {
    const i = renderKeys.value.length;
    renderKeys.value.push(`step-${Date.now()}-${i}`);
  }
};

const canRevealAppendedStep = () => {
  if (renderedCount.value <= 0) return true;
  const current = props.steps[Math.max(0, renderedCount.value - 1)];
  if (!current) return true;
  return current.streaming === false || current.status === 'completed';
};

watch(
  () => props.steps.length,
  (len) => {
    if (len !== lastStepsLength) {
      hasEmittedComplete.value = false;
    }
    // 单步规划会在 stop 时 splice 掉 planning common，steps 先变短再变长。
    // 若不把 revealed 计数同步压回 0，后续写作一次性 push [common, document] 时
    // renderedCount 仍为 1、且当前 common 仍在 streaming，canRevealAppendedStep 为 false，
    // 文档 step 永远不会进入 renderedSteps（用户只看到「进行中：公文写作」）。
    if (len < lastStepsLength) {
      clearRevealTimer();
      renderedCount.value = Math.min(renderedCount.value, len);
      if (renderKeys.value.length > len) {
        renderKeys.value = renderKeys.value.slice(0, len);
      }
    }
    if (len > lastStepsLength) {
      ensureKeys(len);
      if (props.animated === false) {
        renderedCount.value = len;
        emit('step-rendered', {
          stepKey: renderKeys.value[Math.max(0, len - 1)] || '',
          phase: 'revealed',
        });
        hasEmittedComplete.value = true;
        emit('steps-complete', { phase: 'all_completed' });
      } else if (len > 0 && renderedCount.value === 0) {
        renderedCount.value = 1;
        emit('step-rendered', {
          stepKey: renderKeys.value[0] || '',
          phase: 'revealed',
        });
        // 与 scheduleRevealNext 内链式逻辑一致：首条为 common 且同批还有后续 step 时排队展示。
        if (len > 1 && props.steps[0]?.type === 'common') {
          scheduleRevealNext();
        }
      } else if (renderedCount.value < len && !waitingNext.value && canRevealAppendedStep()) {
        // 处理"后续步骤晚到"场景：例如 retrieval stop 后才 append searchResult/writing start。
        scheduleRevealNext();
      }
    }
    lastStepsLength = len;
  },
  { immediate: true }
);

const renderedSteps = computed(() => {
  const n = renderedCount.value;
  return props.steps.slice(0, n).map((step, i) => ({
    step,
    _renderKey: renderKeys.value[i] ?? `step-${i}`,
  }));
});

const showThinkingHint = computed(() => {
  if (props.animated === false) return false;
  if (props.steps.length === 0) return true;
  if (waitingNext.value && renderedCount.value >= 0 && renderedCount.value < props.steps.length) return true;
  // 兜底：当前消息仍在 streaming，但已渲染的最后一步已经 completed，
  // 且下一步尚未到达（例如 retrieval stop 与 writing start 之间）。
  if (!props.streaming) return false;
  if (renderedCount.value <= 0) return true;
  const lastRendered = props.steps[Math.max(0, renderedCount.value - 1)];
  if (!lastRendered) return true;
  const lastCompleted = lastRendered.streaming === false || lastRendered.status === 'completed';
  return lastCompleted;
});

const onStreamingComplete = (key: string) => {
  if (completedKeys.value.has(key)) return;
  completedKeys.value.add(key);

  const currentIndex = renderedCount.value - 1;
  const currentKey = currentIndex >= 0 ? renderKeys.value[currentIndex] : '';
  // 仅当“当前最后一个已展示步骤”完成时，才允许推进到下一步
  if (key !== currentKey) return;

  if (props.animated === false) return;
  if (renderedCount.value >= props.steps.length && !hasEmittedComplete.value) {
    waitingNext.value = false;
    hasEmittedComplete.value = true;
    emit('steps-complete', { phase: 'all_completed' });
    return;
  }
  scheduleRevealNext();
};

onBeforeUnmount(() => {
  clearRevealTimer();
  completedKeys.value.clear();
});
</script>

<style scoped lang="scss">
.agent-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.step-row {
  width: 100%;
}

.step-animate {
  animation: stepSlideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.organizing-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 4px;
  margin-top: 2px;
  color: #6b7280;
  font-size: 14px;
  line-height: 1.5;

  .dots {
    display: inline-flex;
    align-items: center;
    gap: 4px;

    i {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #3b82f6;
      opacity: 0.3;
      animation: dotPulse 1.1s infinite ease-in-out;
    }

    i:nth-child(2) {
      animation-delay: 0.16s;
    }

    i:nth-child(3) {
      animation-delay: 0.32s;
    }
  }
}

@keyframes stepSlideIn {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes dotPulse {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
</style>
