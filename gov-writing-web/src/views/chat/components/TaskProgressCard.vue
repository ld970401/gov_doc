<template>
  <div class="task-progress-card">
    <div
      class="task-progress-header"
      @click="toggleCollapse"
      @mouseenter="isHeaderHover = true"
      @mouseleave="isHeaderHover = false"
    >
      <div class="header-left">
        <div class="header-icon">
          <svg
            viewBox="0 0 1024 1024"
            version="1.1"
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
          >
            <path
              d="M714.666667 917.333333h-405.333334C198.4 917.333333 106.666667 825.6 106.666667 714.666667v-405.333334C106.666667 198.4 198.4 106.666667 309.333333 106.666667h405.333334c110.933333 0 202.666667 91.733333 202.666666 202.666666v405.333334c0 110.933333-91.733333 202.666667-202.666666 202.666666z m-405.333334-746.666666C232.533333 170.666667 170.666667 232.533333 170.666667 309.333333v405.333334c0 76.8 61.866667 138.666667 138.666666 138.666666h405.333334c76.8 0 138.666667-61.866667 138.666666-138.666666v-405.333334c0-76.8-61.866667-138.666667-138.666666-138.666666h-405.333334z m42.666667 330.666666c-59.733333 0-106.666667-46.933333-106.666667-106.666666s46.933333-106.666667 106.666667-106.666667 106.666667 46.933333 106.666667 106.666667-46.933333 106.666667-106.666667 106.666666z m0-149.333333c-23.466667 0-42.666667 19.2-42.666667 42.666667s19.2 42.666667 42.666667 42.666666 42.666667-19.2 42.666667-42.666666-19.2-42.666667-42.666667-42.666667z m384 74.666667H554.666667c-17.066667 0-32-14.933333-32-32S537.6 362.666667 554.666667 362.666667h181.333333c17.066667 0 32 14.933333 32 32s-12.8 32-32 32z m0 234.666666H554.666667c-17.066667 0-32-14.933333-32-32S537.6 597.333333 554.666667 597.333333h181.333333c17.066667 0 32 14.933333 32 32s-12.8 32-32 32z m-401.066667 55.466667c-6.4 0-14.933333-2.133333-19.2-6.4l-42.666666-34.133333c-12.8-10.666667-17.066667-32-4.266667-44.8 10.666667-12.8 32-17.066667 44.8-4.266667l19.2 17.066667L405.333333 576c12.8-12.8 34.133333-10.666667 44.8 2.133333 12.8 12.8 10.666667 34.133333-2.133333 44.8l-91.733333 85.333334c-6.4 4.266667-14.933333 8.533333-21.333334 8.533333z"
            ></path>
          </svg>
        </div>
        <span class="header-text">{{ completedCount }}/{{ totalCount }} 任务已完成</span>
        <el-icon class="collapse-icon" :class="{ 'is-collapsed': collapsed }">
          <ArrowDown />
        </el-icon>
      </div>
      <div class="header-right">
        <button
          v-if="allCompleted && isHeaderHover"
          type="button"
          class="close-btn"
          title="关闭"
          @click.stop="emit('close')"
        >
          <el-icon class="close-icon"><Close /></el-icon>
        </button>
        <el-icon v-else-if="allCompleted" class="check-icon"><Check /></el-icon>
        <el-icon v-else class="loading-icon"><Loading /></el-icon>
      </div>
    </div>
    <div v-show="!collapsed" class="task-list">
      <div v-for="task in tasks" :key="task.id" class="task-item">
        <div class="task-icon">
          <el-icon v-if="task.status === 'completed'" class="icon-completed">
            <CircleCheckFilled />
          </el-icon>
          <el-icon v-else-if="task.status === 'in_progress'" class="icon-loading">
            <Loading />
          </el-icon>
          <el-icon v-else class="icon-pending">
            <CircleClose />
          </el-icon>
        </div>
        <span class="task-title">{{ task.title }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown, Check, CircleCheckFilled, CircleClose, Close, Loading } from '@element-plus/icons-vue';
import { computed, ref } from 'vue';

export interface TaskItem {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed';
}

interface Props {
  tasks?: TaskItem[];
}

const props = withDefaults(defineProps<Props>(), {
  tasks: () => [
    { id: '1', title: '分析当前 SSE 事件流是否支持示例图中的各个步骤展示', status: 'completed' },
    { id: '2', title: '设计后端事件增强方案（推送更细粒度的步骤事件）', status: 'completed' },
    { id: '3', title: '设计前端展示映射方案（将事件数据映射为 UI 卡片）', status: 'completed' },
    { id: '4', title: '输出完整分析报告到 docs 目录', status: 'in_progress' },
    { id: '5', title: '实施后端改造：新增 to_do_list 事件', status: 'pending' },
    { id: '6', title: '实施后端改造：新增 Claw 调用事件', status: 'pending' },
  ],
});

const collapsed = ref(false);
const isHeaderHover = ref(false);

const emit = defineEmits<{
  close: [];
}>();

const completedCount = computed(() => props.tasks.filter((t) => t.status === 'completed').length);
const totalCount = computed(() => props.tasks.length);
const allCompleted = computed(() => completedCount.value === totalCount.value);

const toggleCollapse = () => {
  collapsed.value = !collapsed.value;
};
</script>

<style scoped lang="scss">
.task-progress-card {
  background: #ffffff;
  border-radius: 12px;
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.08),
    0 1px 4px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  transition: box-shadow 0.2s ease;

  &:hover {
    box-shadow:
      0 4px 16px rgba(0, 0, 0, 0.1),
      0 2px 6px rgba(0, 0, 0, 0.06);
  }
}

.task-progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.02);
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 8px;

    .header-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 6px;
      background: rgba(124, 58, 237, 0.08);
    }

    .header-text {
      font-size: 13px;
      font-weight: 500;
      color: #374151;
    }

    .collapse-icon {
      font-size: 14px;
      color: #9ca3af;
      transition: transform 0.2s ease;

      &.is-collapsed {
        transform: rotate(-90deg);
      }
    }
  }

  .header-right {
    display: flex;
    align-items: center;

    .close-btn {
      width: 20px;
      height: 20px;
      border: none;
      border-radius: 50%;
      background: transparent;
      padding: 0;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s ease;

      &:hover {
        background: rgba(0, 0, 0, 0.06);
      }
    }

    .close-icon {
      font-size: 16px;
      color: #9ca3af;
    }

    .check-icon {
      font-size: 16px;
      color: #10b981;
    }

    .loading-icon {
      font-size: 16px;
      color: #9ca3af;
      animation: spin 1s linear infinite;
    }
  }
}

.task-list {
  padding: 4px 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;

  .task-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;

    .icon-completed {
      font-size: 16px;
      color: #10b981;
    }

    .icon-pending {
      font-size: 16px;
      color: #d1d5db;
    }

    .icon-loading {
      font-size: 16px;
      color: #9ca3af;
      animation: spin 1s linear infinite;
    }
  }

  .task-title {
    font-size: 13px;
    color: #6b7280;
    line-height: 1.5;
  }
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
