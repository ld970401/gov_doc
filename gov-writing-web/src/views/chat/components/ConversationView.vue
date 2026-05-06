<template>
  <div class="conversation-view" :class="{ visible: visible }">
    <div v-for="(message, index) in messages" :key="message.id || `m-${index}`" class="message" :class="message.role === 'user' ? 'user-message' : 'assistant-message'">
      <div v-if="message.role === 'user'" class="user-message-content">
        <div v-if="message.attachment" class="user-attachment">
          <el-icon><Upload /></el-icon>
          {{ message.attachment }}
        </div>
        <div class="user-bubble">
          <div v-if="message.skill" class="user-bubble-skill">
            <el-icon><Search /></el-icon>
            {{ message.skill }}
          </div>
          <div class="user-bubble-text">{{ message.content }}</div>
        </div>
      </div>

      <div v-else class="assistant-message-content">
        <AgentSteps
          v-if="getStepList(message).length || isMessageStreaming(message)"
          :steps="getStepList(message)"
          :animated="isMessageStreaming(message)"
          :streaming="isMessageStreaming(message)"
          @step-rendered="(payload) => handleStepRendered(message, payload)"
          @steps-complete="(payload) => handleStepsComplete(message, payload)"
        />

        <div v-if="message.text" class="assistant-text-bubble" :class="{ 'stream-hidden': !message.textVisible, 'stream-visible': message.textVisible }">
          <div v-html="message.text"></div>
        </div>

        <div v-if="!isMessageStreaming(message)" class="msg-actions">
          <button class="msg-action-btn" title="复制" @click="handleCopy(message)">
            <el-icon><CopyDocument /></el-icon>
          </button>
          <button class="msg-action-btn" title="有帮助" @click="handleThumbUp(message)">
            <el-icon><Star /></el-icon>
          </button>
          <button class="msg-action-btn" title="重新生成" @click="handleRefresh(message)">
            <el-icon><Refresh /></el-icon>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CopyDocument, Refresh, Search, Star, Upload } from '@element-plus/icons-vue';
import { computed } from 'vue';
import AgentSteps from './AgentSteps.vue';

const props = defineProps({
  messages: {
    type: Array as () => ChatMessage[],
    default: () => [],
  },
  visible: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits<{
  copy: [message: ChatMessage];
  'thumb-up': [message: ChatMessage];
  refresh: [message: ChatMessage];
  'step-rendered': [payload: { messageId: string; stepKey: string; phase: 'revealed' }];
  'steps-complete': [payload: { messageId: string; phase: 'all_completed' }];
}>();

const handleCopy = (message: ChatMessage) => {
  emit('copy', message);
};

const handleThumbUp = (message: ChatMessage) => {
  emit('thumb-up', message);
};

const handleRefresh = (message: ChatMessage) => {
  emit('refresh', message);
};

const handleStepRendered = (message: ChatMessage, payload: { stepKey: string; phase: 'revealed' }) => {
  emit('step-rendered', {
    messageId: message.id,
    stepKey: payload.stepKey,
    phase: payload.phase,
  });
};

const handleStepsComplete = (message: ChatMessage, payload: { phase: 'all_completed' }) => {
  emit('steps-complete', {
    messageId: message.id,
    phase: payload.phase,
  });
};

const getStepList = (message: ChatMessage): Step[] => {
  return message.steps || [];
};

const isMessageStreaming = (message: ChatMessage) => message.streaming === true;

const messages = computed(() => props.messages);
</script>

<style scoped lang="scss">
.conversation-view {
  display: none;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  max-width: 760px;
  flex: 1;

  &.visible {
    display: flex;
  }
}

.message {
  display: flex;
  flex-direction: column;
  gap: 8px;

  &.user-message {
    align-items: flex-end;
  }

  &.assistant-message {
    align-items: flex-start;
    width: 100%;
    padding: 18px 20px;
    border-radius: 26px;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid rgba(242, 242, 242, 0.95);
    box-shadow: 0 12px 34px rgba(11, 87, 208, 0.08);
  }
}

.user-message-content {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.user-attachment {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: rgba(0, 47, 134, 0.08);
  border: 1px solid rgba(0, 47, 134, 0.15);
  border-radius: 8px;
  font-size: 12px;
  color: var(--primary);

  .el-icon {
    font-size: 15px;
  }
}

.user-bubble {
  background: var(--primary);
  color: #fff;
  padding: 12px 18px;
  border-radius: 20px 20px 4px 20px;
  font-size: 14px;
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.user-bubble-skill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  color: #fff;

  .el-icon {
    font-size: 13px;
  }
}

.user-bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-message-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.assistant-text-bubble {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(226, 232, 240, 0.9);
  font-size: 14px;
  line-height: 1.65;
  color: #1f2937;

  &.stream-hidden {
    opacity: 0.35;
  }

  &.stream-visible {
    opacity: 1;
  }
}

.msg-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.msg-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.92);
  color: #64748b;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease;

  &:hover {
    border-color: rgba(0, 47, 134, 0.18);
    color: var(--primary);
    background: rgba(235, 243, 254, 0.85);
  }

  .el-icon {
    font-size: 16px;
  }
}
</style>
