import { nextTick, ref } from 'vue';

export const useChatScrollController = () => {
  const scrollContainerRef = ref<HTMLElement | null>(null);
  const autoScroll = ref(true);
  const isRestoringHistory = ref(false);
  const isSwitchingSession = ref(false);
  let scrollIgnoreUntil = 0;

  const canAutoScroll = () =>
    autoScroll.value && !isRestoringHistory.value && !isSwitchingSession.value;

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth', force = false) => {
    if (!force && !autoScroll.value) return;
    scrollIgnoreUntil = Date.now() + (behavior === 'smooth' ? 800 : 80);
    nextTick(() => {
      requestAnimationFrame(() => {
        const container = scrollContainerRef.value;
        if (!container) return;
        container.scrollTo({ top: container.scrollHeight, behavior });
        if (force) {
          setTimeout(() => {
            const latest = scrollContainerRef.value;
            if (!latest) return;
            latest.scrollTop = latest.scrollHeight;
          }, 50);
        }
      });
    });
  };

  const handleScroll = () => {
    if (Date.now() < scrollIgnoreUntil) return;
    const container = scrollContainerRef.value;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    autoScroll.value = isAtBottom;
  };

  const handleWheel = (e: WheelEvent) => {
    if (e.deltaY < 0) autoScroll.value = false;
  };

  return {
    scrollContainerRef,
    autoScroll,
    isRestoringHistory,
    isSwitchingSession,
    canAutoScroll,
    scrollToBottom,
    handleScroll,
    handleWheel,
  };
};
