<template>
  <div v-loading="loading" class="viewer">
    <div class="screen">
      <img
        v-if="src && !failed"
        :src="src"
        class="frame"
        alt="第一视角帧"
        @load="failed = false"
        @error="failed = true"
      />
      <div v-else class="frame-empty">
        <el-icon :size="24"><Picture /></el-icon>
        <span>{{ loading ? '加载帧图像…' : '当前 episode 没有可用帧' }}</span>
      </div>

      <img v-if="showMask && maskSrc" :src="maskSrc" class="mask" alt="可通行区域掩膜" />

      <div class="hud-top">
        <span class="hud-chip step">FRAME {{ (frame?.idx ?? 0) + 1 }} / {{ total || 0 }}</span>
        <span class="hud-chip action" :class="frame?.action || 'forward'">
          {{ actionLabel(frame?.action) }}
        </span>
        <span class="hud-chip mono">{{ latency }} ms</span>
        <span class="hud-chip mono">W{{ frame?.window_len ?? 0 }}</span>
      </div>

      <div v-if="!src && !loading" class="empty-hint">
        Mock 演示帧由服务端按逐帧元数据生成
      </div>

      <div class="hud-bottom">
        <div class="instruction">{{ instruction || '—' }}</div>
        <div class="hud-meta mono">
          x {{ poseText(0) }} · y {{ poseText(1) }} · z {{ poseText(2) }} · TOKENS
          {{ frame?.tokens_after_prune ?? 0 }}
          <span v-if="frame?.slow_update" class="slow">· 慢记忆更新</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  maskSrc: { type: String, default: '' },
  frame: { type: Object, default: null },
  total: { type: Number, default: 0 },
  instruction: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  showMask: { type: Boolean, default: false },
})

const failed = ref(false)
const latency = computed(() => Number(props.frame?.latency_ms || 0).toFixed(1))

const ACTION_LABELS = {
  forward: '前进',
  left: '左转',
  right: '右转',
  stop: '停止',
  turn_left: '左转',
  turn_right: '右转',
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action || '未知'
}

function poseText(axis) {
  const value = props.frame?.pose?.[axis]
  return value === undefined ? '—' : Number(value).toFixed(2)
}

watch(
  () => props.src,
  () => {
    failed.value = false
  },
)
</script>

<style scoped>
.viewer {
  width: 100%;
  height: 100%;
}

.screen {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: radial-gradient(circle at 50% 20%, #1b2c47, #0b1220 70%);
}

.frame {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.mask {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0.5;
  mix-blend-mode: screen;
  pointer-events: none;
}

.frame-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #6f89ab;
  font-size: 12px;
}

.hud-top {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}

.hud-chip {
  padding: 3px 8px;
  border-radius: 5px;
  background: rgba(9, 17, 30, 0.68);
  border: 1px solid rgba(120, 155, 200, 0.22);
  color: #dbe7f7;
  font-size: 11px;
  letter-spacing: 0.4px;
  backdrop-filter: blur(4px);
}

.hud-chip.step {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.hud-chip.action {
  color: #08111f;
  font-weight: 600;
  border: none;
}

.hud-chip.action.forward {
  background: #6aa7ff;
}

.hud-chip.action.left {
  background: #4ade80;
}

.hud-chip.action.right {
  background: #fbbf24;
}

.hud-chip.action.stop {
  background: #cbd5e1;
}

.hud-bottom {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 32px 16px 12px;
  background: linear-gradient(180deg, transparent, rgba(5, 11, 20, 0.88));
  pointer-events: none;
}

.instruction {
  color: #eaf2ff;
  font-size: 13px;
  line-height: 1.55;
  max-width: 92%;
}

.hud-meta {
  margin-top: 6px;
  color: #8fa8c7;
  font-size: 11px;
}

.slow {
  color: #fbbf24;
}

.empty-hint {
  position: absolute;
  left: 12px;
  bottom: 66px;
  color: #5f7695;
  font-size: 11px;
}
</style>
