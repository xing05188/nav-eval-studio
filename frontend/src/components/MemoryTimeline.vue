<template>
  <div class="memory">
    <div class="legend">
      <span><i class="dot normal" />上下文长度</span>
      <span><i class="dot slow" />慢记忆更新</span>
      <span><i class="dot prune" />token 裁剪</span>
    </div>
    <div ref="container" class="chart" :style="{ height: `${height}px` }">
      <canvas ref="canvas" @click="onClick" />
    </div>
    <div class="ticks">
      <span>0</span>
      <span class="mono">{{ maxValue.toLocaleString() }} token</span>
      <span>{{ frames.length }} 帧</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  frames: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  height: { type: Number, default: 74 },
})

const emit = defineEmits(['seek'])

const container = ref(null)
const canvas = ref(null)
let ctx = null
let observer = null
const maxValue = computed(() =>
  Math.max(1, ...props.frames.map((frame) => Number(frame.ctx_len || 0))),
)

function draw() {
  const rect = container.value?.getBoundingClientRect()
  if (!rect || !canvas.value) return
  const dpr = window.devicePixelRatio || 1
  const width = rect.width
  const height = rect.height
  canvas.value.width = Math.max(1, Math.round(width * dpr))
  canvas.value.height = Math.max(1, Math.round(height * dpr))
  ctx = canvas.value.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)

  const frames = props.frames
  if (!frames.length) return

  const bottom = height - 5
  const gap = frames.length > 90 ? 0 : 1
  const barWidth = Math.max(1, width / frames.length - gap)
  const scale = (bottom - 6) / maxValue.value

  frames.forEach((frame, i) => {
    const value = Number(frame.ctx_len || 0)
    const barHeight = Math.max(2, value * scale)
    const x = (i * width) / frames.length
    const y = bottom - barHeight
    const active = i === props.index
    if (active) {
      ctx.fillStyle = '#2f6fed'
    } else if (frame.slow_update) {
      ctx.fillStyle = '#f8c56b'
    } else {
      ctx.fillStyle = '#d8e6f9'
    }
    ctx.beginPath()
    ctx.roundRect(x, y, barWidth, barHeight, 2)
    ctx.fill()

    if (frame.tokens_after_prune < frame.tokens_before_prune) {
      ctx.fillStyle = '#ef8a8a'
      ctx.fillRect(x, y - 3, barWidth, 2)
    }
  })

  const [current] = [frames[props.index]]
  if (current) {
    const x = (props.index * width) / frames.length
    ctx.strokeStyle = '#2f6fed'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(x + barWidth / 2, 0)
    ctx.lineTo(x + barWidth / 2, bottom)
    ctx.stroke()
  }
}

function onClick(event) {
  if (!props.frames.length) return
  const rect = canvas.value.getBoundingClientRect()
  const ratio = (event.clientX - rect.left) / rect.width
  const index = Math.min(
    props.frames.length - 1,
    Math.max(0, Math.floor(ratio * props.frames.length)),
  )
  emit('seek', index)
}

onMounted(() => {
  draw()
  observer = new ResizeObserver(draw)
  observer.observe(container.value)
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
  ctx = null
})

watch(() => [props.frames, props.index], draw, { deep: true })
</script>

<style scoped>
.memory {
  width: 100%;
}

.legend {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 11px;
  color: #7d8fa8;
  margin-bottom: 6px;
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  display: inline-block;
}

.dot.normal {
  background: #d8e6f9;
}

.dot.slow {
  background: #f8c56b;
}

.dot.prune {
  background: #ef8a8a;
}

.chart {
  width: 100%;
  background: #fbfdff;
  border: 1px solid #edf2fa;
  border-radius: 6px;
}

canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: pointer;
}

.ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 10px;
  color: #9aa8bc;
}
</style>
