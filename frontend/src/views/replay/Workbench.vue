<template>
  <div class="page replay-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">轨迹回放</h2>
        <div class="page-subtitle">俯视轨迹、第一视角、动作时间轴与记忆状态四区联动</div>
      </div>
      <div class="header-actions">
        <el-select
          v-model="taskId"
          filterable
          placeholder="选择评测任务"
          class="task-select"
          :disabled="!tasks.length"
          @change="onTaskChange"
        >
          <el-option
            v-for="task in tasks"
            :key="task.id"
            :value="task.id"
            :label="`${task.name} (#${task.id})`"
          />
        </el-select>
        <el-select
          v-model="rowId"
          filterable
          placeholder="选择 episode"
          class="episode-select"
          :disabled="!episodes.length"
          @change="onEpisodeChange"
        >
          <el-option
            v-for="item in episodes"
            :key="item.id"
            :value="item.id"
            :label="`#${item.episode_key} · ${item.success || item.status === 'success' ? '成功' : '失败'} · ${item.steps} 步`"
          />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="reloadAll">刷新</el-button>
        <el-button v-if="taskId" :icon="VideoPlay" @click="router.push(`/tasks/${taskId}`)">
          任务详情
        </el-button>
      </div>
    </div>

    <section v-if="!tasks.length && !loading" class="panel empty-wrap">
      <el-empty description="暂无已完成 Episode 的任务，请先运行一次评测" />
    </section>

    <section v-else-if="!replay && !loading" class="panel empty-wrap">
      <el-empty description="该任务暂无可回放的 episode" />
    </section>

    <template v-else>
      <div v-if="replay" class="summary-strip panel">
        <div class="summary-item">
          <span class="summary-label">结果</span>
          <el-tag size="small" :type="row.success ? 'success' : 'danger'" effect="plain">
            {{ row.success ? '成功' : '失败' }}
          </el-tag>
        </div>
        <div class="summary-item"><span class="summary-label">SPL</span><b>{{ percent(row.spl) }}</b></div>
        <div class="summary-item"><span class="summary-label">NE</span><b>{{ number(row.ne) }} m</b></div>
        <div class="summary-item"><span class="summary-label">nDTW</span><b>{{ percent(row.ndtw) }}</b></div>
        <div class="summary-item"><span class="summary-label">步数</span><b>{{ row.steps }}</b></div>
        <div class="summary-item"><span class="summary-label">帧数</span><b>{{ frames.length }}</b></div>
        <div class="summary-item"><span class="summary-label">平均时延</span><b>{{ row.latency_avg_ms }} ms</b></div>
        <div v-if="row.failure_reason" class="summary-item">
          <span class="summary-label">归因</span>
          <el-tag size="small" type="warning" effect="plain">{{ failureLabel(row.failure_reason) }}</el-tag>
        </div>
        <div class="summary-task">{{ taskName }} · {{ replay.task.dataset }}</div>
      </div>

      <el-alert
        v-if="replay && !frames.length"
        class="no-frames"
        type="warning"
        :closable="false"
        show-icon
        title="该 episode 没有逐帧元数据，仅显示汇总指标与参考路径"
        description="真实推理适配器未输出逐帧记录时会出现此情况；Mock 演示任务可完整回放。"
      />

      <div v-loading="loading" class="workbench">
        <section class="panel map-panel">
          <div class="panel-header">
            <span class="panel-title">俯视轨迹</span>
            <span class="sub mono" v-if="replay">#{{ replay.episode.episode_key }}</span>
          </div>
          <div class="panel-body map-body">
            <TrajectoryCanvas
              :trajectory="trajectory"
              :reference="reference"
              :start="startPoint"
              :goal="goalPoint"
              :bounds="bounds"
              :index="index"
              :yaw="currentFrame?.yaw || 0"
              :height="430"
              :show-reference="showReference"
              :show-corridor="showCorridor"
              :show-trail="showTrail"
              @seek="seek"
            />
            <div class="map-legend">
              <span><i class="legend-line reference" />参考路径</span>
              <span><i class="legend-line traveled" />已走轨迹</span>
              <span><i class="legend-dot start" />起点</span>
              <span><i class="legend-dot goal" />终点</span>
            </div>
          </div>
        </section>

        <section class="panel viewer-panel">
          <div class="panel-header">
            <span class="panel-title">第一视角</span>
            <div class="viewer-head-right">
              <el-tag size="small" effect="plain" type="info">
                {{ config.modality || '—' }} · {{ config.memory_policy || '—' }}
              </el-tag>
            </div>
          </div>
          <div class="panel-body viewer-body">
            <FrameViewer
              :src="frameUrl(index)"
              :mask-src="maskSrc"
              :frame="currentFrame"
              :total="frames.length"
              :instruction="replay?.episode.instruction || ''"
              :loading="loading"
              :show-mask="showMask && Boolean(maskSrc)"
            />
            <div class="viewer-foot">
              <span class="mono">POSE {{ poseText }}</span>
              <span class="mono">SPEED {{ motionSpeed.toFixed(2) }} m/s</span>
              <span class="mono">CTX {{ currentFrame?.ctx_len ?? '—' }}</span>
            </div>
          </div>
        </section>

        <aside class="panel side-panel">
          <div class="panel-header">
            <span class="panel-title">运行状态</span>
            <el-tag v-if="playing" size="small" type="success" effect="plain">播放中</el-tag>
          </div>
          <el-tabs v-model="sideTab" class="side-tabs">
            <el-tab-pane label="记忆状态" name="memory">
              <div class="side-block">
                <div class="kv"><span>窗口帧数</span><b>{{ currentFrame?.window_len ?? '—' }} / {{ config.history_len || '—' }}</b></div>
                <div class="kv"><span>慢记忆更新</span><b :class="{ warn: currentFrame?.slow_update }">{{ currentFrame?.slow_update ? '是' : '否' }}</b></div>
                <div class="kv">
                  <span>裁剪前 / 后</span>
                  <b class="mono">{{ currentFrame?.tokens_before_prune ?? '—' }} → {{ currentFrame?.tokens_after_prune ?? '—' }}</b>
                </div>
                <div class="kv"><span>上下文长度</span><b class="mono">{{ currentFrame?.ctx_len ?? '—' }}</b></div>
                <div class="kv"><span>单步时延</span><b class="mono">{{ currentFrame?.latency_ms ?? '—' }} ms</b></div>
              </div>

              <MemoryTimeline :frames="frames" :index="index" @seek="seek" />

              <div class="mini-stats">
                <div class="mini-stat">
                  <div class="mini-label">慢更新</div>
                  <div class="mini-value">{{ summary.slow_updates ?? 0 }}</div>
                </div>
                <div class="mini-stat">
                  <div class="mini-label">裁剪帧</div>
                  <div class="mini-value">{{ summary.pruned_frames ?? 0 }}</div>
                </div>
                <div class="mini-stat">
                  <div class="mini-label">峰值 ctx</div>
                  <div class="mini-value mono">{{ summary.max_ctx_len ?? 0 }}</div>
                </div>
              </div>

              <div class="side-card">
                <div class="side-card-title">记忆策略</div>
                <div class="policy-row">
                  <el-tag size="small" effect="plain">{{ config.memory_policy || '—' }}</el-tag>
                  <span class="mono muted">slow = {{ config.slow_update_interval || '—' }} 步</span>
                </div>
                <div class="side-note">慢更新帧在曲线上以橙色标记；发生 token 裁剪的帧顶部有红色短线。</div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="几何 / 运动" name="geometry">
              <div class="side-block">
                <div class="switch-row">
                  <span>参考路径</span>
                  <el-switch v-model="showReference" size="small" />
                </div>
                <div class="switch-row">
                  <span>参考走廊</span>
                  <el-switch v-model="showCorridor" size="small" />
                </div>
                <div class="switch-row">
                  <span>已走轨迹</span>
                  <el-switch v-model="showTrail" size="small" />
                </div>
                <div class="switch-row">
                  <span>可通行掩膜</span>
                  <el-switch v-model="showMask" size="small" :disabled="!maskSrc" />
                </div>
                <div v-if="!maskSrc" class="side-note">
                  当前 episode 没有深度帧，掩膜与局部点云叠加不可用。
                </div>
              </div>

              <div class="side-block">
                <div class="kv"><span>当前位置</span><b class="mono">{{ poseText }}</b></div>
                <div class="kv"><span>偏航角</span><b class="mono">{{ yawText }}</b></div>
                <div class="kv"><span>瞬时速度</span><b class="mono">{{ motionSpeed.toFixed(2) }} m/s</b></div>
                <div class="kv"><span>参考路径长</span><b class="mono">{{ referenceLength.toFixed(2) }} m</b></div>
                <div class="kv"><span>已走距离</span><b class="mono">{{ traveledLength.toFixed(2) }} m</b></div>
              </div>

              <div class="side-card">
                <div class="side-card-title">运动曲线</div>
                <LineChart
                  v-if="speedSeries.length"
                  :x-axis="speedAxis"
                  :series="speedChartSeries"
                  y-name="m/s"
                  :height="130"
                />
                <div v-else class="side-note">暂无速度采样</div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </aside>

        <section class="panel timeline-panel">
          <div class="panel-header">
            <span class="panel-title">动作时间轴</span>
            <span class="sub">拖动定位 · 方向键单步 · 空格播放</span>
          </div>
          <div class="panel-body timeline-body">
            <div class="controls">
              <el-button-group>
                <el-button size="small" :icon="DArrowLeft" @click="seek(0)" />
                <el-button size="small" :icon="ArrowLeft" @click="seek(index - 1)" />
                <el-button
                  size="small"
                  type="primary"
                  :icon="playing ? VideoPause : VideoPlay"
                  @click="togglePlay"
                />
                <el-button size="small" :icon="ArrowRight" @click="seek(index + 1)" />
                <el-button size="small" :icon="DArrowRight" @click="seek(frames.length - 1)" />
              </el-button-group>

              <el-slider
                v-model="index"
                class="slider"
                :min="0"
                :max="Math.max(frames.length - 1, 0)"
                :show-tooltip="false"
                @change="stop"
              />

              <span class="mono counter">{{ frames.length ? index + 1 : 0 }} / {{ frames.length }}</span>

              <el-select v-model="playSpeed" size="small" class="speed-select">
                <el-option :value="0.5" label="0.5×" />
                <el-option :value="1" label="1×" />
                <el-option :value="2" label="2×" />
                <el-option :value="4" label="4×" />
              </el-select>
              <el-switch v-model="loop" size="small" active-text="循环" />
            </div>

            <div v-if="frames.length" ref="actionStrip" class="action-strip">
              <button
                v-for="(frame, i) in frames"
                :key="frame.idx"
                class="action-chip"
                :class="[frame.action, { active: i === index, slow: frame.slow_update }]"
                :title="`第 ${i + 1} 步 · ${actionLabel(frame.action)} · ${frame.latency_ms} ms`"
                @click="seek(i)"
              >
                <span class="chip-idx">{{ i + 1 }}</span>
                <span class="chip-label">{{ actionShort(frame.action) }}</span>
              </button>
            </div>
            <div v-else class="sub">没有逐帧元数据，暂无法显示动作序列。</div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  DArrowLeft,
  DArrowRight,
  Refresh,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'
import TrajectoryCanvas from '@/components/TrajectoryCanvas.vue'
import FrameViewer from '@/components/FrameViewer.vue'
import MemoryTimeline from '@/components/MemoryTimeline.vue'
import LineChart from '@/components/LineChart.vue'
import { failureLabel } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const tasks = ref([])
const episodes = ref([])
const taskId = ref(null)
const rowId = ref(null)
const replay = ref(null)
const index = ref(0)
const loading = ref(false)
const playing = ref(false)
const loop = ref(false)
const playSpeed = ref(1)
const sideTab = ref('memory')

const showReference = ref(true)
const showCorridor = ref(true)
const showTrail = ref(true)
const showMask = ref(false)

const actionStrip = ref(null)
let timer = null

const frames = computed(() => replay.value?.frames || [])
const currentFrame = computed(() => frames.value[index.value] || null)
const row = computed(() => replay.value?.row || {})
const summary = computed(() => replay.value?.summary || {})
const config = computed(() => replay.value?.config || {})
const trajectory = computed(() => replay.value?.geometry?.trajectory || [])
const reference = computed(() => replay.value?.geometry?.reference || [])
const bounds = computed(() => replay.value?.geometry?.bounds || null)
const startPoint = computed(() => replay.value?.geometry?.start || null)
const goalPoint = computed(() => replay.value?.geometry?.goal || null)
const speedSeries = computed(() => replay.value?.geometry?.speed_series || [])
const taskName = computed(() => replay.value?.task?.name || tasks.value.find((t) => t.id === taskId.value)?.name || '')

const maskSrc = computed(() => {
  const url = replay.value?.geometry?.mask_url
  if (!url) return ''
  return `${url}?token=${encodeURIComponent(auth.token)}`
})

const poseText = computed(() => {
  const pose = currentFrame.value?.pose
  if (!pose) return '—'
  return pose.map((value) => Number(value).toFixed(2)).join(' / ')
})

const yawText = computed(() => {
  const yaw = currentFrame.value?.yaw
  return yaw === undefined ? '—' : `${Number(yaw).toFixed(2)} rad`
})

const ACTION_LABELS = {
  forward: '前进',
  left: '左转',
  right: '右转',
  stop: '停止',
  turn_left: '左转',
  turn_right: '右转',
}
const ACTION_SHORT = { forward: '前', left: '左', right: '右', stop: '停' }

function actionLabel(action) {
  return ACTION_LABELS[action] || action || '未知'
}

function actionShort(action) {
  return ACTION_SHORT[action] || actionLabel(action).slice(0, 1)
}

function percent(value) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function number(value) {
  if (value === null || value === undefined) return '—'
  return Number(value).toFixed(2)
}

const motionSpeed = computed(() => {
  if (!currentFrame.value || index.value === 0) return 0
  const prev = frames.value[index.value - 1]
  const current = currentFrame.value
  const dt = Number(current.t || 0) - Number(prev.t || 0)
  if (dt <= 0) return 0
  const dx = current.pose[0] - prev.pose[0]
  const dz = current.pose[2] - prev.pose[2]
  return Math.hypot(dx, dz) / dt
})

const traveledLength = computed(() => {
  let total = 0
  for (let i = 1; i <= index.value && i < trajectory.value.length; i += 1) {
    const prev = trajectory.value[i - 1]
    const current = trajectory.value[i]
    total += Math.hypot(current[0] - prev[0], current[1] - prev[1])
  }
  return total
})

const referenceLength = computed(() => {
  let total = 0
  for (let i = 1; i < reference.value.length; i += 1) {
    const prev = reference.value[i - 1]
    const current = reference.value[i]
    total += Math.hypot(current[0] - prev[0], current[1] - prev[1])
  }
  return total
})

const speedAxis = computed(() => speedSeries.value.map((item) => Number(item[0]).toFixed(1)))
const speedChartSeries = computed(() => [
  {
    name: '速度',
    data: speedSeries.value.map((item) => Number(item[1])),
    color: '#2f6fed',
    area: true,
  },
])

function frameUrl(frameIndex) {
  if (!replay.value || !taskId.value || !rowId.value) return ''
  return `/api/replay/${taskId.value}/${rowId.value}/frame/${frameIndex}?token=${encodeURIComponent(auth.token)}`
}

function seek(next) {
  if (!frames.value.length) return
  stop()
  index.value = Math.min(frames.value.length - 1, Math.max(0, Number(next) || 0))
}

function schedule() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    if (!playing.value) return
    if (index.value >= frames.value.length - 1) {
      if (loop.value) {
        index.value = 0
        schedule()
      } else {
        stop()
      }
      return
    }
    index.value += 1
    schedule()
  }, Math.max(120, 700 / playSpeed.value))
}

function start() {
  if (frames.value.length < 2) return
  if (index.value >= frames.value.length - 1) index.value = 0
  playing.value = true
  schedule()
}

function stop() {
  playing.value = false
  clearTimeout(timer)
}

function togglePlay() {
  if (playing.value) stop()
  else start()
}

function prefetch() {
  if (!replay.value) return
  for (const delta of [-2, -1, 1, 2]) {
    const target = index.value + delta
    if (target >= 0 && target < frames.value.length) {
      const image = new Image()
      image.src = frameUrl(target)
    }
  }
  const node = actionStrip.value?.querySelector('.action-chip.active')
  if (node) node.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
}

async function loadTasks() {
  const data = await api.tasks({ page_size: 100 })
  tasks.value = (data.items || []).filter(
    (item) =>
      ['succeeded', 'failed', 'canceled'].includes(item.status) &&
      Number(item.metrics?.episodes || 0) > 0,
  )
}

async function loadEpisodes() {
  if (!taskId.value) {
    episodes.value = []
    return
  }
  const data = await api.taskEpisodes(taskId.value, { page_size: 200 })
  episodes.value = (data.items || []).filter((item) =>
    ['success', 'failed'].includes(item.status),
  )
}

function pickDefaultEpisode() {
  return (
    episodes.value.find((item) => item.status === 'success' && item.steps > 0)?.id ??
    episodes.value.find((item) => item.steps > 0)?.id ??
    episodes.value[0]?.id ??
    null
  )
}

async function loadReplay() {
  if (!taskId.value || !rowId.value) {
    replay.value = null
    return
  }
  loading.value = true
  stop()
  try {
    replay.value = await api.replayEpisode(taskId.value, rowId.value)
    index.value = 0
    prefetch()
  } catch {
    replay.value = null
  } finally {
    loading.value = false
  }
}

function syncQuery() {
  router.replace({
    path: '/replay',
    query: { task_id: taskId.value, row_id: rowId.value },
  })
}

async function onTaskChange() {
  stop()
  rowId.value = null
  replay.value = null
  await loadEpisodes()
  rowId.value = pickDefaultEpisode()
  if (rowId.value) await loadReplay()
  syncQuery()
}

async function onEpisodeChange() {
  await loadReplay()
  syncQuery()
}

async function reloadAll() {
  loading.value = true
  try {
    await loadTasks()
    if (!tasks.value.some((item) => item.id === taskId.value)) {
      taskId.value = tasks.value[0]?.id ?? null
    }
    if (taskId.value) {
      await loadEpisodes()
      if (!episodes.value.some((item) => item.id === rowId.value)) {
        rowId.value = pickDefaultEpisode()
      }
      if (rowId.value) await loadReplay()
    } else {
      replay.value = null
    }
  } finally {
    loading.value = false
  }
}

function onKeydown(event) {
  const tag = event.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return
  if (event.code === 'Space') {
    event.preventDefault()
    togglePlay()
  } else if (event.code === 'ArrowLeft') {
    event.preventDefault()
    seek(index.value - 1)
  } else if (event.code === 'ArrowRight') {
    event.preventDefault()
    seek(index.value + 1)
  }
}

watch(index, prefetch)
watch(playSpeed, () => {
  if (playing.value) schedule()
})

onMounted(async () => {
  loading.value = true
  try {
    await loadTasks()
    const queryTask = Number(route.query.task_id)
    const queryRow = Number(route.query.row_id)
    taskId.value = tasks.value.some((item) => item.id === queryTask)
      ? queryTask
      : tasks.value[0]?.id ?? null

    if (taskId.value) {
      await loadEpisodes()
      rowId.value = episodes.value.some((item) => item.id === queryRow)
        ? queryRow
        : pickDefaultEpisode()
      if (rowId.value) await loadReplay()
    }
    if (taskId.value) syncQuery()
  } finally {
    loading.value = false
  }
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  stop()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.replay-page {
  padding-bottom: 24px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-select {
  width: 230px;
}

.episode-select {
  width: 260px;
}

.empty-wrap {
  padding: 50px 0;
}

.summary-strip {
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 10px 18px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.no-frames {
  margin-bottom: 14px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
}

.summary-item b {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-weight: 600;
  color: #1f2937;
}

.summary-label {
  color: var(--nav-text-muted);
}

.summary-task {
  margin-left: auto;
  font-size: 12px;
  color: #9aa6b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}

.workbench {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr) 330px;
  grid-template-areas:
    'map viewer side'
    'timeline timeline side';
  gap: 14px;
  align-items: start;
}

.map-panel {
  grid-area: map;
}

.viewer-panel {
  grid-area: viewer;
}

.side-panel {
  grid-area: side;
  position: sticky;
  top: 70px;
}

.timeline-panel {
  grid-area: timeline;
}

.panel-header .sub {
  color: var(--nav-text-muted);
  font-size: 12px;
}

.map-body {
  padding: 10px 12px 12px;
}

.map-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
  font-size: 11px;
  color: #7d8fa8;
  flex-wrap: wrap;
}

.legend-line {
  display: inline-block;
  width: 16px;
  height: 2px;
  margin-right: 5px;
  vertical-align: 3px;
}

.legend-line.reference {
  border-top: 2px dashed #9db0c9;
}

.legend-line.traveled {
  background: #2f6fed;
}

.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 5px;
}

.legend-dot.start {
  background: #16a34a;
}

.legend-dot.goal {
  background: #dc2626;
}

.viewer-body {
  padding: 12px 12px 10px;
}

.viewer-head-right {
  display: flex;
  gap: 6px;
}

.viewer-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  font-size: 11px;
  color: #7d8fa8;
  flex-wrap: wrap;
}

.side-panel {
  padding-bottom: 6px;
}

.side-tabs {
  padding: 0 14px;
}

.side-tabs :deep(.el-tabs__header) {
  margin: 0 0 10px;
}

.side-tabs :deep(.el-tabs__item) {
  font-size: 12px;
  padding: 0 12px;
}

.side-block {
  padding: 4px 0 12px;
  border-bottom: 1px dashed #eef2f9;
  margin-bottom: 12px;
}

.side-block:last-child {
  border-bottom: none;
}

.kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--nav-text-muted);
  padding: 4px 0;
}

.kv b {
  color: #1f2937;
  font-weight: 500;
  text-align: right;
}

.kv b.warn {
  color: #d97706;
}

.mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.mini-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0;
}

.mini-stat {
  background: #f8faff;
  border: 1px solid #eef3fa;
  border-radius: 7px;
  padding: 8px;
  text-align: center;
}

.mini-label {
  font-size: 11px;
  color: #93a2b8;
}

.mini-value {
  margin-top: 4px;
  font-size: 16px;
  font-weight: 600;
  color: #23324a;
}

.side-card {
  background: #fbfdff;
  border: 1px solid #eef3fa;
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 10px;
}

.side-card-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}

.policy-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.side-note {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.6;
  color: #93a2b8;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #475569;
  padding: 5px 0;
}

.timeline-body {
  padding: 10px 16px 14px;
}

.controls {
  display: flex;
  align-items: center;
  gap: 14px;
}

.slider {
  flex: 1;
  min-width: 120px;
}

.counter {
  font-size: 12px;
  color: #64748b;
  min-width: 66px;
  text-align: right;
}

.speed-select {
  width: 78px;
}

.action-strip {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding: 10px 2px 4px;
  scrollbar-width: thin;
}

.action-chip {
  flex: 0 0 auto;
  border: 1px solid #e6edf8;
  background: #fbfdff;
  border-radius: 5px;
  padding: 3px 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  cursor: pointer;
  transition: all 0.15s ease;
  color: #64748b;
}

.action-chip:hover {
  border-color: #b9cef0;
}

.action-chip .chip-idx {
  font-size: 9px;
  color: #a4b2c6;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.action-chip .chip-label {
  font-size: 11px;
}

.action-chip.forward {
  background: #f1f7ff;
}

.action-chip.left {
  background: #f0fdf6;
}

.action-chip.right {
  background: #fffaeb;
}

.action-chip.slow {
  box-shadow: inset 0 -2px 0 #f8c56b;
}

.action-chip.active {
  border-color: #2f6fed;
  background: #2f6fed;
  color: #fff;
  transform: translateY(-1px);
}

.action-chip.active .chip-idx {
  color: #cfe0ff;
}

.sub {
  color: var(--nav-text-muted);
  font-size: 12px;
}

@media (max-width: 1440px) {
  .workbench {
    grid-template-columns: 320px minmax(0, 1fr) 300px;
  }
}

@media (max-width: 1180px) {
  .workbench {
    grid-template-columns: 1fr;
    grid-template-areas:
      'viewer'
      'map'
      'side'
      'timeline';
  }

  .side-panel {
    position: static;
  }
}
</style>
