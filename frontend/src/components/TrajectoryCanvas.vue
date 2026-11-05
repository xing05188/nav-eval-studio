<template>
  <div ref="container" class="trajectory" :style="{ height: `${height}px` }">
    <canvas
      ref="canvas"
      @mousemove="onMove"
      @mouseleave="onLeave"
      @click="onClick"
    />
    <div v-if="!trajectory.length && !reference.length" class="empty">
      <el-icon :size="22"><Position /></el-icon>
      <span>暂无轨迹数据</span>
    </div>
    <div v-else-if="trajectory.length" class="hint">点击轨迹定位到对应帧</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  trajectory: { type: Array, default: () => [] },
  reference: { type: Array, default: () => [] },
  start: { type: Array, default: null },
  goal: { type: Array, default: null },
  bounds: { type: Object, default: null },
  index: { type: Number, default: 0 },
  yaw: { type: Number, default: 0 },
  height: { type: Number, default: 360 },
  showReference: { type: Boolean, default: true },
  showCorridor: { type: Boolean, default: true },
  showTrail: { type: Boolean, default: true },
})

const emit = defineEmits(['seek'])

const container = ref(null)
const canvas = ref(null)
const hoverIndex = ref(-1)
let ctx = null
let observer = null
let view = { scale: 1, ox: 0, oy: 0, width: 0, height: 0 }

function allPoints() {
  const points = [...props.trajectory]
  if (props.showReference) points.push(...props.reference)
  if (props.start) points.push(props.start)
  if (props.goal) points.push(props.goal)
  return points.filter((point) => Array.isArray(point) && point.length >= 2)
}

function layout() {
  const rect = container.value?.getBoundingClientRect()
  if (!rect) return
  const dpr = window.devicePixelRatio || 1
  const node = canvas.value
  node.width = Math.max(1, Math.round(rect.width * dpr))
  node.height = Math.max(1, Math.round(rect.height * dpr))
  ctx = node.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const points = allPoints()
  const width = rect.width
  const height = rect.height
  if (!points.length) {
    view = { scale: 1, ox: width / 2, oy: height / 2, width, height }
    return
  }
  const xs = points.map((point) => point[0])
  const zs = points.map((point) => point[1])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minZ = Math.min(...zs)
  const maxZ = Math.max(...zs)
  const padding = 34
  const scale = Math.min(
    (width - padding * 2) / Math.max(maxX - minX, 0.8),
    (height - padding * 2) / Math.max(maxZ - minZ, 0.8),
  )
  view = {
    scale,
    ox: width / 2 - ((minX + maxX) / 2) * scale,
    oy: height / 2 - ((minZ + maxZ) / 2) * scale,
    width,
    height,
    minX,
    maxX,
    minZ,
    maxZ,
  }
}

function project(point) {
  return [view.ox + point[0] * view.scale, view.oy + point[1] * view.scale]
}

function drawGrid() {
  if (!ctx) return
  const { width, height } = view
  ctx.save()
  ctx.strokeStyle = '#eef3fa'
  ctx.lineWidth = 1
  const step = view.scale > 40 ? 1 : view.scale > 16 ? 2 : 5
  if (view.minX !== undefined) {
    for (let x = Math.ceil(view.minX / step) * step; x <= view.maxX; x += step) {
      const [sx] = project([x, view.minZ])
      ctx.beginPath()
      ctx.moveTo(sx, 0)
      ctx.lineTo(sx, height)
      ctx.stroke()
    }
    for (let z = Math.ceil(view.minZ / step) * step; z <= view.maxZ; z += step) {
      const [, sy] = project([view.minX, z])
      ctx.beginPath()
      ctx.moveTo(0, sy)
      ctx.lineTo(width, sy)
      ctx.stroke()
    }
  }
  ctx.restore()
}

function strokePath(points, color, width, dash = []) {
  if (!ctx || points.length < 2) return
  ctx.save()
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.setLineDash(dash)
  ctx.beginPath()
  points.forEach((point, index) => {
    const [x, y] = project(point)
    if (index === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
  ctx.restore()
}

function marker(point, color, label, ring = false) {
  if (!ctx || !point) return
  const [x, y] = project(point)
  ctx.save()
  ctx.beginPath()
  ctx.arc(x, y, ring ? 7 : 6, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()
  ctx.lineWidth = 2
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  if (label) {
    ctx.fillStyle = '#334155'
    ctx.font = '600 11px "Segoe UI", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'bottom'
    ctx.fillText(label, x, y - 10)
  }
  ctx.restore()
}

function drawCurrent() {
  const frame = props.trajectory[props.index]
  if (!ctx || !frame) return
  const [x, y] = project(frame)
  let angle = props.yaw
  if (props.index > 0) {
    const prev = props.trajectory[props.index - 1]
    angle = Math.atan2(frame[1] - prev[1], frame[0] - prev[0])
  }
  ctx.save()
  ctx.translate(x, y)
  ctx.beginPath()
  ctx.arc(0, 0, 13, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(47,111,237,0.16)'
  ctx.fill()

  ctx.rotate(angle)
  ctx.beginPath()
  ctx.moveTo(11, 0)
  ctx.lineTo(-6, 6)
  ctx.lineTo(-3, 0)
  ctx.lineTo(-6, -6)
  ctx.closePath()
  ctx.fillStyle = '#2f6fed'
  ctx.fill()
  ctx.lineWidth = 1.5
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  ctx.restore()
}

function draw() {
  if (!ctx || !container.value) return
  const { width, height } = view
  ctx.clearRect(0, 0, width, height)
  drawGrid()

  if (props.showCorridor && props.reference.length > 1) {
    strokePath(props.reference, 'rgba(47,111,237,0.10)', 26)
    strokePath(props.reference, 'rgba(47,111,237,0.16)', 14)
  }
  if (props.showReference && props.reference.length > 1) {
    strokePath(props.reference, '#9db0c9', 1.6, [6, 5])
    ctx.save()
    ctx.fillStyle = '#b6c5d9'
    props.reference.forEach((point) => {
      const [x, y] = project(point)
      ctx.beginPath()
      ctx.arc(x, y, 2.4, 0, Math.PI * 2)
      ctx.fill()
    })
    ctx.restore()
  }

  if (props.trajectory.length > 1) {
    strokePath(props.trajectory, '#d8e3f2', 2)
    const upto = props.trajectory.slice(0, props.index + 1)
    if (props.showTrail) strokePath(upto, '#2f6fed', 3)
  }

  marker(props.start, '#16a34a', 'S')
  marker(props.goal, '#dc2626', 'G', true)

  if (hoverIndex.value >= 0 && hoverIndex.value !== props.index) {
    const point = props.trajectory[hoverIndex.value]
    if (point) {
      const [x, y] = project(point)
      ctx.save()
      ctx.beginPath()
      ctx.arc(x, y, 4, 0, Math.PI * 2)
      ctx.fillStyle = '#94a3b8'
      ctx.fill()
      ctx.restore()
    }
  }

  drawCurrent()
}

function nearestIndex(event) {
  if (!props.trajectory.length) return -1
  const rect = canvas.value.getBoundingClientRect()
  const mx = event.clientX - rect.left
  const my = event.clientY - rect.top
  let best = -1
  let distance = Infinity
  props.trajectory.forEach((point, index) => {
    const [x, y] = project(point)
    const value = (x - mx) ** 2 + (y - my) ** 2
    if (value < distance) {
      distance = value
      best = index
    }
  })
  return distance <= 26 ** 2 ? best : -1
}

function onMove(event) {
  const index = nearestIndex(event)
  if (index !== hoverIndex.value) {
    hoverIndex.value = index
    draw()
  }
}

function onLeave() {
  hoverIndex.value = -1
  draw()
}

function onClick(event) {
  const index = nearestIndex(event)
  if (index >= 0) emit('seek', index)
}

function redraw() {
  layout()
  draw()
}

onMounted(() => {
  redraw()
  observer = new ResizeObserver(redraw)
  observer.observe(container.value)
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

watch(
  () => [
    props.trajectory,
    props.reference,
    props.index,
    props.yaw,
    props.showReference,
    props.showCorridor,
    props.showTrail,
    props.start,
    props.goal,
  ],
  redraw,
  { deep: true },
)
</script>

<style scoped>
.trajectory {
  position: relative;
  width: 100%;
  background: #fbfdff;
  border-radius: 8px;
  overflow: hidden;
}

canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
}

.empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #9aa8bc;
  font-size: 12px;
  background: #fbfdff;
}

.hint {
  position: absolute;
  left: 10px;
  bottom: 8px;
  font-size: 11px;
  color: #a5b2c5;
  pointer-events: none;
}
</style>
