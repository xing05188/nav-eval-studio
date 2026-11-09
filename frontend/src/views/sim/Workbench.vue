<template>
  <div class="page sim-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">交互式仿真</h2>
        <div class="page-subtitle">选一局 episode，在真实场景里手动驾驶机器狗，左侧看第一视角、右侧看轨迹</div>
      </div>
      <div class="header-actions">
        <el-select
          v-model="datasetId"
          filterable
          placeholder="选择数据集"
          class="dataset-select"
          :disabled="locked"
          @change="onDatasetChange"
        >
          <el-option
            v-for="item in datasets"
            :key="item.id"
            :value="item.id"
            :label="`${item.name}${item.version ? ` · ${item.version}` : ''}（${item.episode_count || 0} 局）`"
          />
        </el-select>
        <el-select
          v-model="episodeId"
          filterable
          placeholder="选择 episode"
          class="episode-select"
          :disabled="locked || !episodes.length"
          :loading="loadingEpisodes"
          @change="onEpisodeChange"
        >
          <el-option
            v-for="item in episodes"
            :key="item.id"
            :value="item.id"
            :label="`#${item.episode_key} · ${item.scene_id}`"
          />
        </el-select>
        <el-select
          v-model="gpuId"
          placeholder="GPU 跟随配置"
          class="gpu-select"
          clearable
          :disabled="locked || !canControl || !gpuOptions.length"
          @visible-change="(visible) => visible && loadGpus()"
        >
          <el-option
            v-for="item in gpuOptions"
            :key="item.index"
            :value="item.index"
            :label="gpuOptionLabel(item)"
          />
        </el-select>
        <el-button
          type="primary"
          :icon="VideoPlay"
          :loading="starting"
          :disabled="!canControl || !episodeId || busy"
          @click="startSim"
        >
          启动仿真
        </el-button>
        <el-button :icon="SwitchButton" :disabled="!canControl || status === 'idle'" @click="stopSim">
          停止仿真
        </el-button>
        <el-tag :type="statusType" effect="plain">{{ statusText }}</el-tag>
      </div>
    </div>

    <section v-if="datasetsLoaded && !datasets.length" class="panel empty-datasets">
      <el-empty :image-size="70" description="平台还没有登记数据集：先到「数据集」页扫描或手动登记，再回来启动仿真" />
    </section>
    <section v-else-if="datasetId && !loadingEpisodes && !episodes.length" class="panel empty-datasets">
      <el-empty
        :image-size="70"
        description="该数据集没有可用的 episode：训练集/大规模数据默认只登记路径，需到「数据集」页手动扫描后再回来"
      />
    </section>

    <section v-if="selectedEpisode" class="preview-strip panel">
      <span class="preview-scene">{{ selectedEpisode.scene_id }}</span>
      <span class="preview-item">成功半径 <b>{{ goalRadius.toFixed(1) }}</b> m</span>
      <span class="preview-item">
        起点 <b>{{ pointText(startPoint) }}</b> → 终点 <b>{{ pointText(goalPoint) }}</b>
      </span>
      <span class="preview-instruction" :title="selectedEpisode.instruction">
        {{ selectedEpisode.instruction || '（该 episode 没有指令文本）' }}
      </span>
    </section>

    <el-alert
      v-if="status === 'ready' && viewerWarning"
      class="warn-bar"
      type="warning"
      :title="viewerWarning"
      show-icon
      :closable="false"
    />

    <div class="sim-main">
      <section class="panel viewer-panel">
        <div class="panel-header">
          <span class="panel-title">仿真画面 · 第一视角 ｜ 俯视轨迹</span>
          <div class="panel-tools">
            <span class="panel-meta">
              <template v-if="status === 'ready'">
                {{ state.fps ? `${state.fps.toFixed(0)} fps` : '实时' }} · 步数 {{ state.steps }}
                <template v-if="state.gpu_id !== null && state.gpu_id !== undefined">
                  · GPU{{ state.gpu_id }}
                </template>
                <template v-if="state.clients > 0">· 观看 {{ state.clients }}</template>
              </template>
              <template v-else>{{ statusText }}</template>
            </span>
            <span v-if="recordText" class="panel-meta record-meta">录制 {{ recordText }}</span>
            <span class="panel-meta">第三视角</span>
            <el-switch v-model="pipOn" size="small" :disabled="!pipEnabled" @change="togglePip" />
            <span class="panel-meta">机器狗</span>
            <el-switch v-model="robotOn" size="small" :disabled="!robotEnabled" @change="toggleRobot" />
            <el-button
              size="small"
              :icon="Download"
              :loading="exportBusy || downloading"
              :disabled="!exportEnabled"
              @click="onExport"
            >
              {{ exportLabel }}
            </el-button>
          </div>
        </div>

        <div class="stage">
          <!-- 不要用 :key 重建 <img>：重建会把最后一帧丢掉，断流瞬间整块变黑；
               只换 src（带 k 参数）时浏览器会保留旧帧直到新流出图 -->
          <img
            v-if="streamSrc"
            class="stream"
            :src="streamSrc"
            alt="机器狗第一视角画面"
            @error="onStreamError"
            @load="onStreamLoad"
          />
          <div v-if="modelDriving" class="stage-badge">
            <span class="stage-dot" />模型驾驶中 · {{ latencyText }}
          </div>
          <div v-if="status === 'idle'" class="stage-layer">
            <el-icon class="stage-icon"><Aim /></el-icon>
            <p>选择 episode 后点「启动仿真」</p>
            <p class="stage-hint">首次加载场景约 5–20 秒</p>
          </div>
          <div v-else-if="status === 'loading'" class="stage-layer">
            <el-skeleton animated :rows="4" class="stage-skeleton" />
            <p>正在加载场景…（首次约 5–20 秒）</p>
          </div>
          <div v-else-if="status === 'error'" class="stage-layer stage-error">
            <el-icon class="stage-icon"><WarningFilled /></el-icon>
            <p>{{ state.message || '仿真启动失败' }}</p>
            <el-button size="small" :icon="Refresh" :disabled="!canControl" @click="startSim">重试</el-button>
          </div>
          <div v-else-if="status === 'stopped'" class="stage-layer">
            <el-icon class="stage-icon"><SwitchButton /></el-icon>
            <p>会话已停止，点「启动仿真」重新开始</p>
          </div>
          <div v-else-if="streamError" class="stage-layer stage-error">
            <el-icon class="stage-icon"><WarningFilled /></el-icon>
            <p>{{ streamError }}</p>
            <div class="stage-actions">
              <el-button size="small" :icon="Refresh" @click="retryStream">重新连接画面</el-button>
              <el-button size="small" text @click="reloadPage">刷新页面</el-button>
            </div>
          </div>
        </div>

        <div class="policy-bar">
          <span class="policy-title">
            <el-icon><MagicStick /></el-icon>
            模型驾驶
          </span>
          <el-select
            v-model="policyGpuId"
            size="small"
            class="policy-gpu-select"
            placeholder="GPU 默认"
            clearable
            :disabled="!canControl || !gpuOptions.length || policyBusy"
            @visible-change="(visible) => visible && loadGpus()"
          >
            <el-option
              v-for="item in gpuOptions"
              :key="item.index"
              :value="item.index"
              :label="`GPU${item.index}`"
            />
          </el-select>
          <el-select
            v-model="modelId"
            size="small"
            class="policy-select"
            placeholder="选择模型"
            :disabled="!canControl || !models.length || policyBusy"
            :loading="loadingModels"
          >
            <el-option v-for="item in models" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
          <el-button
            size="small"
            type="primary"
            :disabled="!policyCanStart"
            :loading="policy.status === 'loading'"
            @click="startPolicy"
          >
            {{ policy.status === 'error' ? '重试' : '启用模型' }}
          </el-button>
          <el-button size="small" :disabled="!policyCanToggle" @click="togglePolicyPause">
            {{ policy.paused ? '恢复模型驾驶' : '暂停' }}
          </el-button>
          <el-button size="small" :disabled="!policyCanStop" @click="stopPolicy">停止</el-button>
          <el-tag size="small" :type="policyTagType" effect="plain">{{ policyText }}</el-tag>
          <span v-if="policyStats" class="policy-stats">{{ policyStats }}</span>
          <span v-if="policy.status === 'error'" class="policy-error">{{ policy.message }}</span>
        </div>

        <div class="controls">
          <el-button
            class="ctrl-btn"
            :class="{ 'is-pressed': pressed.has('forward') }"
            :disabled="!controlsEnabled"
            @click="act('forward', true)"
          >
            前进 <kbd>↑ / W</kbd>
          </el-button>
          <el-button
            class="ctrl-btn"
            :class="{ 'is-pressed': pressed.has('left') }"
            :disabled="!controlsEnabled"
            @click="act('left', true)"
          >
            左转 <kbd>← / A</kbd>
          </el-button>
          <el-button
            class="ctrl-btn"
            :class="{ 'is-pressed': pressed.has('right') }"
            :disabled="!controlsEnabled"
            @click="act('right', true)"
          >
            右转 <kbd>→ / D</kbd>
          </el-button>
          <el-button
            class="ctrl-btn ctrl-stop"
            :class="{ 'is-pressed': pressed.has('stop') }"
            :disabled="!controlsEnabled"
            @click="act('stop', true)"
          >
            停止 <kbd>空格</kbd>
          </el-button>
          <el-button class="ctrl-btn" :icon="Back" :disabled="!resetEnabled" @click="act('reset', true)">
            回起点
          </el-button>
          <el-button
            class="ctrl-btn"
            :class="{ 'is-oracle': state.oracle }"
            :icon="Position"
            :disabled="!oracleEnabled"
            @click="toggleOracle"
          >
            {{ state.oracle ? '停止 Oracle' : 'Oracle 走一遍' }}
          </el-button>
        </div>
        <p v-if="!canControl" class="ctrl-hint">当前角色为只读，仅可查看画面与读数。</p>
        <p v-else class="ctrl-hint">
          点击或按住键盘即可操控：前进 0.25 m、转向 15°，每次操作立即生效。
        </p>

        <div class="readout-strip">
          <div class="readout">
            <span class="readout-label">步数</span>
            <span class="readout-value">{{ state.steps }}<i>/500</i></span>
          </div>
          <div class="readout">
            <span class="readout-label">到目标</span>
            <span class="readout-value">{{ Number(state.distance || 0).toFixed(2) }}<i>m</i></span>
          </div>
          <div class="readout">
            <span class="readout-label">成功半径</span>
            <span class="readout-value">{{ goalRadius.toFixed(1) }}<i>m</i></span>
          </div>
          <div class="readout">
            <span class="readout-label">朝向</span>
            <span class="readout-value">{{ yawText }}<i>deg</i></span>
          </div>
          <div class="readout">
            <span class="readout-label">测地 / SPL</span>
            <span class="readout-value">{{ Number(state.geodesic || 0).toFixed(2) }}<i>m · {{ splText }}</i></span>
          </div>
          <div class="readout">
            <span class="readout-label">动作来源</span>
            <span class="readout-value">{{ sourceText }}<i>队列 {{ state.pending }}</i></span>
          </div>
          <div class="readout readout-wide">
            <span class="readout-label">场景</span>
            <span class="readout-text">{{ state.episode?.scene || selectedEpisode?.scene_id || '—' }}</span>
          </div>
          <div class="readout readout-wide readout-instruction">
            <span class="readout-label">指令</span>
            <span class="readout-text">{{ state.episode?.instruction || selectedEpisode?.instruction || '—' }}</span>
          </div>
        </div>
        <p v-if="state.message" class="state-message">{{ state.message }}</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Aim,
  Back,
  Download,
  MagicStick,
  Position,
  Refresh,
  SwitchButton,
  VideoPlay,
  WarningFilled,
} from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()

const datasets = ref([])
const datasetsLoaded = ref(false)
const episodes = ref([])
const datasetId = ref(null)
const episodeId = ref(null)
const meta = ref(null)
const starting = ref(false)
const loadingEpisodes = ref(false)
const streamKey = ref(0)
const streamStuck = ref(false)
const streamError = ref('')
const pressed = reactive(new Set())

const models = ref([])
const modelId = ref(null)
const loadingModels = ref(false)

// GPU 选择：null = 跟随配置（sim.gpu_ids[0] / policy.gpu_id），选中值只对下一次启动生效
const gpus = ref([])
const gpuId = ref(null)
const policyGpuId = ref(null)
const gpuOptions = computed(() => (gpus.value || []).filter((item) => item.index !== undefined))

const state = reactive({
  status: 'idle',
  session_id: '',
  episode: null,
  steps: 0,
  distance: 0,
  done: false,
  pose: null,
  trail: [],
  radius: 0,
  fps: 0,
  frame_seq: 0,
  message: '',
  warning: null,
  pending: 0,
  last_action_source: 'manual',
  geodesic: 0,
  ne: 0,
  shortest: 0,
  spl: 0,
  success: false,
  oracle: false,
  pip: false,
  pip_available: false,
  robot: false,
  robot_available: false,
  gpu_id: null,
  clients: 0,
})

// 第三视角画中画（后端 state.pip / state.pip_available）
const pipOn = ref(true)
// 画中画里的机器狗模型（后端 state.robot / state.robot_available）
const robotOn = ref(true)

// 会话录制与 mp4 导出（后端 state.recording）
const recording = reactive({
  frames: 0,
  seconds: 0,
  fps: 0,
  max_frames: 0,
  dropped: 0,
  export: { status: 'idle', progress: 0, frames: 0, encoded: 0, filename: '', size_bytes: 0, message: '' },
})
const downloading = ref(false)
let lastExportStatus = 'idle'

// 模型驾驶状态（后端 GET /api/sim/state 的 policy 字段）
const policy = reactive({
  status: 'off',
  model: '',
  gpu_id: null,
  paused: false,
  message: '',
  last_latency_ms: 0,
  avg_latency_ms: 0,
  infer_count: 0,
  actions_done: 0,
  inferring_s: 0,
  load_seconds: 0,
})

const canControl = computed(() => ['admin', 'operator'].includes(auth.role))
const busy = computed(() => ['loading', 'ready'].includes(state.status))
const locked = computed(() => busy.value)
const controlsEnabled = computed(() => canControl.value && state.status === 'ready' && !state.done)
// 停下之后仍允许回起点重新开一局，所以复位不受 state.done 限制
const resetEnabled = computed(() => canControl.value && state.status === 'ready')
// 已停止的局不能再启动 oracle（后端会 409），但允许手动点「停止 Oracle」
const oracleEnabled = computed(
  () => canControl.value && state.status === 'ready' && (!state.done || state.oracle),
)

const selectedEpisode = computed(
  () => episodes.value.find((item) => item.id === episodeId.value) || null,
)
const startPoint = computed(
  () => state.episode?.start || selectedEpisode.value?.start_pose || null,
)
const goalPoint = computed(
  () => state.episode?.goal || selectedEpisode.value?.goal_pose || null,
)
const goalRadius = computed(() => {
  const radius = Number(state.radius || meta.value?.meta?.goal_radius || 3)
  return Number.isFinite(radius) && radius > 0 ? radius : 3
})
const viewerWarning = computed(() => {
  if (streamStuck.value) return '画面超过 3 秒没有新帧，正在自动重连…'
  return state.warning || ''
})
const yawText = computed(() => Number(state.pose?.yaw_deg || 0).toFixed(0))
// SPL 只在拿到最短路径长度时才有意义（官方 geodesic 或 navmesh 现算）
const splText = computed(() =>
  Number(state.shortest || 0) > 0 ? Number(state.spl || 0).toFixed(2) : '—',
)
const SOURCE_TEXT = { model: '模型', oracle: 'Oracle', manual: '手动' }
const sourceText = computed(() => SOURCE_TEXT[state.last_action_source] || '手动')

// ---- 第三视角画中画 / 录制导出 ----
const pipEnabled = computed(
  () => canControl.value && state.status === 'ready' && state.pip_available,
)
const robotEnabled = computed(
  () => canControl.value && state.status === 'ready' && state.robot_available,
)
const recordText = computed(() => {
  const seconds = Number(recording.seconds || 0)
  if (!recording.frames || !seconds) return ''
  const mm = Math.floor(seconds / 60)
  const ss = Math.round(seconds % 60)
  const limit = recording.max_frames ? ` · ${recording.frames}/${recording.max_frames} 帧` : ''
  return `${mm}:${String(ss).padStart(2, '0')}${limit}`
})
const exportBusy = computed(() => recording.export.status === 'encoding')
const exportReady = computed(() => recording.export.status === 'ready')
// 停会话之后仍可导出（后端保留了上一局的帧目录），所以不看 state.status
const exportEnabled = computed(
  () => canControl.value && recording.frames > 0 && !exportBusy.value,
)
const exportLabel = computed(() => {
  if (exportBusy.value) return `导出中 ${Math.round((recording.export.progress || 0) * 100)}%`
  if (exportReady.value) return '下载 mp4'
  return '导出 mp4'
})

// ---- 模型驾驶 ----
const policyBusy = computed(() => ['loading', 'ready', 'running', 'paused'].includes(policy.status))
const policyCanStart = computed(
  () => canControl.value && state.status === 'ready' && Boolean(modelId.value) && !policyBusy.value,
)
const policyCanToggle = computed(
  () => canControl.value && ['ready', 'running', 'paused'].includes(policy.status),
)
const policyCanStop = computed(() => canControl.value && policy.status !== 'off')
// 只有模型队列在驱动前进时才算"模型驾驶中"（接管后立刻消失）
const modelDriving = computed(
  () => policy.status === 'running' && state.last_action_source === 'model' && !state.done,
)
const latencyText = computed(() => {
  const ms = policy.last_latency_ms || policy.avg_latency_ms || 0
  return ms ? `${(ms / 1000).toFixed(1)} s/次` : '首次推理中…'
})

const POLICY_TEXT = {
  off: '未启用',
  loading: '模型加载中',
  ready: '模型就绪',
  running: '模型驾驶中',
  paused: '已暂停',
  error: '模型出错',
}
const POLICY_TYPE = {
  off: 'info',
  loading: 'warning',
  ready: 'success',
  running: 'success',
  paused: 'warning',
  error: 'danger',
}
const policyText = computed(() => {
  const base = POLICY_TEXT[policy.status] || policy.status
  if (policy.status === 'paused' && policy.message) return `${base}：${policy.message}`
  return base
})
const policyTagType = computed(() => POLICY_TYPE[policy.status] || 'info')
const policyStats = computed(() => {
  if (!['ready', 'running', 'paused'].includes(policy.status)) return ''
  const parts = [
    `GPU${policy.gpu_id}`,
    `第 ${policy.infer_count} 次推理`,
    `已执行 ${policy.actions_done} 步`,
    `队列 ${state.pending}`,
  ]
  if (policy.status === 'running' && policy.inferring_s > 0) {
    parts.push(`推理中 ${policy.inferring_s.toFixed(1)} s`)
  }
  return parts.join(' · ')
})

const STATUS_TEXT = {
  idle: '未启动',
  loading: '加载中',
  ready: '运行中',
  stopped: '已停止',
  error: '出错',
}
const STATUS_TYPE = {
  idle: 'info',
  loading: 'warning',
  ready: 'success',
  stopped: 'info',
  error: 'danger',
}
const statusText = computed(() => STATUS_TEXT[state.status] || state.status)
const statusType = computed(() => STATUS_TYPE[state.status] || 'info')

const streamSrc = computed(() => {
  if (state.status !== 'ready' || !state.session_id || !auth.token) return ''
  return `/api/sim/stream?token=${encodeURIComponent(auth.token)}&k=${streamKey.value}`
})

function pointText(point) {
  if (!Array.isArray(point) || point.length < 3) return '—'
  return `${Number(point[0]).toFixed(1)}, ${Number(point[2]).toFixed(1)}`
}

// el-select 的 clearable 清空后给的是 ''，后端字段是 int|null，这里统一成 null
function gpuValue(value) {
  return value === '' || value === undefined || value === null ? null : value
}

// 选项上直接给"还剩多少显存"，换卡时不用再去系统页比对
function gpuOptionLabel(item) {
  const total = Number(item.memory_total_mb || 0)
  const used = Number(item.memory_used_mb || 0)
  if (!total) return `GPU${item.index}`
  const free = Math.max(0, total - used) / 1024
  return `GPU${item.index} · 空闲 ${free.toFixed(1)}G`
}

function applyState(data) {
  Object.assign(state, {
    status: data.status,
    session_id: data.session_id,
    episode: data.episode,
    steps: data.steps || 0,
    distance: data.distance || 0,
    done: Boolean(data.done),
    pose: data.pose || null,
    trail: data.trail || [],
    radius: data.radius || 0,
    fps: data.fps || 0,
    frame_seq: data.frame_seq || 0,
    message: data.message || '',
    warning: data.warning || null,
    pending: data.pending || 0,
    last_action_source: data.last_action_source || 'manual',
    geodesic: data.geodesic || 0,
    ne: data.ne || 0,
    shortest: data.shortest || 0,
    spl: data.spl || 0,
    success: Boolean(data.success),
    oracle: Boolean(data.oracle),
    pip: Boolean(data.pip),
    pip_available: Boolean(data.pip_available),
    robot: Boolean(data.robot),
    robot_available: Boolean(data.robot_available),
    gpu_id: data.gpu_id ?? null,
    clients: data.clients || 0,
  })
  pipOn.value = Boolean(data.pip)
  robotOn.value = Boolean(data.robot)
  if (data.recording) {
    Object.assign(recording, {
      frames: data.recording.frames || 0,
      seconds: data.recording.seconds || 0,
      fps: data.recording.fps || 0,
      max_frames: data.recording.max_frames || 0,
      dropped: data.recording.dropped || 0,
    })
    const job = data.recording.export || {}
    Object.assign(recording.export, {
      status: job.status || 'idle',
      progress: job.progress || 0,
      frames: job.frames || 0,
      encoded: job.encoded || 0,
      filename: job.filename || '',
      size_bytes: job.size_bytes || 0,
      message: job.message || '',
    })
    // 编码是后台线程，等到这里的状态跳成 ready 再提示一次，用户不用盯着进度条
    if (recording.export.status === 'ready' && lastExportStatus !== 'ready') {
      ElMessage.success(`mp4 导出完成（${(recording.export.size_bytes / 1024 / 1024).toFixed(1)} MB），点「下载 mp4」保存`)
    }
    lastExportStatus = recording.export.status
  }
  if (data.policy) Object.assign(policy, data.policy)
  else Object.assign(policy, { status: 'off', paused: false, message: '' })
  if (data.frame_seq !== lastSeq) {
    lastSeq = data.frame_seq || 0
    lastSeqAt = Date.now()
    streamStuck.value = false
    streamError.value = ''
    reconnectCount = 0            // 帧恢复了，重连计数归零
  }
}

// 轮询去重：接口慢的时候不要把一个请求堆成十几个（浏览器只有 6 条连接）
let refreshing = false
const refresh = () => {
  if (refreshing) return
  refreshing = true
  api
    .simState()
    .then(applyState)
    .catch(() => {})          // 拦截器已经弹过提示，这里不再刷屏
    .finally(() => {
      refreshing = false
    })
}

// 画面断了：保留最后一帧，只给提示 + 手动重连，不偷偷无限重连把连接占满
function onStreamError() {
  streamError.value = '画面连接失败：可能是同时观看人数已满或会话已结束，请点下面按钮重连'
  streamStuck.value = false
}

function onStreamLoad() {
  streamError.value = ''
  streamStuck.value = false
  reconnectCount = 0
  lastSeqAt = Date.now()
}

// 浏览器对同一域名只有 6 条连接：卡死后重连按钮可能也发不出去，刷新页面能一次性回收
function reloadPage() {
  window.location.reload()
}

function retryStream() {
  streamError.value = ''
  streamStuck.value = false
  reconnectCount = 0
  lastSeqAt = Date.now()
  streamKey.value += 1
}

function loadDatasets() {
  api
    .datasets()
    .then((data) => {
      // 该接口直接返回数组（不像 episodes 那样包一层分页），两种形状都兼容
      datasets.value = Array.isArray(data) ? data : data?.items || []
      if (datasets.value.length) {
        // 默认选第一个「有 episode」的数据集：train / scalevln 这类只登记路径，解析出来是空的
        const preferred =
          datasets.value.find((item) => (item.episode_count || 0) > 0) || datasets.value[0]
        datasetId.value = preferred.id
        loadEpisodes()
      }
    })
    .catch(console.error)
    .finally(() => {
      datasetsLoaded.value = true
    })
}

function loadEpisodes() {
  if (!datasetId.value) return
  loadingEpisodes.value = true
  episodes.value = []
  episodeId.value = null
  api
    .episodes(datasetId.value, { page: 1, page_size: 100 })
    .then((data) => {
      episodes.value = data.items || []
      episodeId.value = episodes.value[0]?.id || null
      loadMeta()
    })
    .catch(console.error)
    .finally(() => {
      loadingEpisodes.value = false
    })
}

function loadMeta() {
  if (!datasetId.value || !episodeId.value) {
    meta.value = null
    return
  }
  api.episode(datasetId.value, episodeId.value).then((data) => {
    meta.value = data
  }).catch(console.error)
}

function onDatasetChange() {
  loadEpisodes()
}

function onEpisodeChange() {
  loadMeta()
}

function startSim() {
  if (!episodeId.value) return
  starting.value = true
  api
    .simStart({ episode_id: episodeId.value, gpu_id: gpuValue(gpuId.value) })
    .then((data) => {
      lastSeq = -1
      lastSeqAt = Date.now()
      Object.assign(state, {
        status: 'loading',
        session_id: data.session_id,
        episode: data.episode,
        steps: 0,
        distance: 0,
        done: false,
        pose: null,
        trail: [],
        radius: data.episode?.radius || 0,
        fps: 0,
        frame_seq: 0,
        message: '',
        warning: data.warning || null,
        pending: 0,
        last_action_source: 'manual',
        geodesic: 0,
        ne: 0,
        shortest: 0,
        spl: 0,
        success: false,
        oracle: false,
        gpu_id: data.gpu_id ?? null,
      })
      streamError.value = ''
      streamStuck.value = false
      reconnectCount = 0
      streamKey.value += 1
      // 新会话是新的录制目录，先把上一局的帧数/导出状态清掉
      Object.assign(recording, { frames: 0, seconds: 0, dropped: 0 })
      Object.assign(recording.export, {
        status: 'idle', progress: 0, frames: 0, encoded: 0, filename: '', size_bytes: 0, message: '',
      })
      lastExportStatus = 'idle'
    })
    .catch((error) => {
      console.error(error)
      state.status = 'error'
      state.message = error?.message || '仿真启动失败'
    })
    .finally(() => {
      starting.value = false
    })
}

function loadModels() {
  loadingModels.value = true
  api
    .models()
    .then((data) => {
      const list = Array.isArray(data) ? data : data?.items || []
      models.value = list.filter((item) => item.family === 'streamvln')
      if (models.value.length && !modelId.value) modelId.value = models.value[0].id
    })
    .catch(console.error)
    .finally(() => {
      loadingModels.value = false
    })
}

function loadGpus() {
  api
    .gpus()
    .then((data) => {
      gpus.value = Array.isArray(data) ? data : data?.items || []
    })
    .catch(console.error)
}

function startPolicy() {
  if (!policyCanStart.value) return
  api
    .simPolicyStart({ model_id: modelId.value, gpu_id: gpuValue(policyGpuId.value) })
    .then((data) => {
      Object.assign(policy, data.policy || { status: 'loading' })
      if (data.warning) ElMessage.warning(data.warning)
      else ElMessage.success('模型加载中，约 12 秒后开始自动驾驶')
      refresh()
    })
    .catch((error) => {
      console.error(error)
      ElMessage.error(error?.message || '模型启用失败')
    })
}

function stopPolicy() {
  api
    .simPolicyStop()
    .then(() => {
      Object.assign(policy, { status: 'off', paused: false, message: '', infer_count: 0 })
      ElMessage.success('模型已停止，正在后台释放显存')
      refresh()
    })
    .catch(console.error)
}

function toggleOracle() {
  const next = !state.oracle
  api
    .simOracle(next)
    .then((data) => {
      Object.assign(state, {
        oracle: Boolean(data.oracle),
        last_action_source: data.last_action_source || state.last_action_source,
        done: Boolean(data.done),
        steps: data.steps ?? state.steps,
        distance: data.distance ?? state.distance,
        message: data.message || '',
      })
      if (next) {
        ElMessage.info('Oracle 开始沿最短路径走，按方向键即可接管')
        if (policy.status === 'running') Object.assign(policy, { status: 'paused', paused: true, message: '已切到 Oracle 驾驶' })
      }
      refresh()
    })
    .catch((error) => {
      console.error(error)
      ElMessage.error(error?.message || 'Oracle 启动失败')
    })
}

function togglePip(value) {
  api
    .simPip(value)
    .then((data) => {
      state.pip = Boolean(data.pip)
      state.pip_available = Boolean(data.pip_available)
    })
    .catch((error) => {
      console.error(error)
      pipOn.value = state.pip          // 失败就把开关拨回去
    })
}

function toggleRobot(value) {
  api
    .simRobot(value)
    .then((data) => {
      state.robot = Boolean(data.robot)
      state.robot_available = Boolean(data.robot_available)
    })
    .catch((error) => {
      console.error(error)
      robotOn.value = state.robot     // 失败就把开关拨回去
    })
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'sim.mp4'
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function onExport() {
  if (!exportEnabled.value) return
  if (exportReady.value) {
    downloading.value = true
    api
      .simExportFile()
      .then((blob) => downloadBlob(blob, recording.export.filename))
      .catch(console.error)
      .finally(() => {
        downloading.value = false
      })
    return
  }
  api
    .simExport()
    .then((data) => {
      Object.assign(recording.export, { status: data.status || 'encoding', progress: data.progress || 0 })
      lastExportStatus = recording.export.status
      if (data.status === 'error') ElMessage.warning(data.message || '导出失败')
      else ElMessage.info(`开始导出 mp4（${data.frames || 0} 帧），完成后会提示下载`)
      refresh()
    })
    .catch(console.error)
}

function togglePolicyPause() {
  api
    .simPolicyPause(!policy.paused)
    .then((data) => {
      Object.assign(policy, data.policy || {})
      refresh()
    })
    .catch((error) => {
      console.error(error)
      ElMessage.error(error?.message || '操作失败')
    })
}

function stopSim() {
  api
    .simStop(state.session_id || 'current')
    .then(() => {
      resetState()
      ElMessage.success('仿真已停止，显存已释放')
    })
    .catch(console.error)
}

function resetState() {
  Object.assign(state, {
    status: 'idle',
    session_id: '',
    steps: 0,
    distance: 0,
    done: false,
    pose: null,
    trail: [],
    fps: 0,
    frame_seq: 0,
    message: '',
    pending: 0,
    last_action_source: 'manual',
    geodesic: 0,
    ne: 0,
    shortest: 0,
    spl: 0,
    success: false,
    oracle: false,
  })
  Object.assign(policy, { status: 'off', paused: false, message: '', infer_count: 0 })
  streamStuck.value = false
  streamError.value = ''
  reconnectCount = 0
  lastSeq = -1
}

let lastActAt = 0
// 同一时刻只允许一条操控请求在飞：按住方向键时按 160ms 连发，后端一慢就会堆出
// 十几条请求，把浏览器对同一域名的 6 条连接占满（连 /state 和重连画面都发不出去，
// 整页看起来"卡死"）。这里只保留最后一次操作，当前请求结束后再发。
let actInFlight = false
let actNext = null

function act(action, force = false) {
  if (!canControl.value || state.status !== 'ready') return
  if (action !== 'reset' && state.done) return
  const now = performance.now()
  if (!force && now - lastActAt < 90) return
  lastActAt = now
  if (actInFlight) {
    actNext = action
    return
  }
  sendAct(action)
}

function sendAct(action) {
  actInFlight = true
  api
    .simAct(action)
    .then((data) => {
      state.steps = data.steps
      state.distance = data.distance
      state.done = data.done
      state.message = data.message || ''
      // 后端收到手动动作后会把模型暂停；这里先就地改状态，不用等下一次轮询
      if (policy.status === 'running' || policy.status === 'ready') {
        policy.status = 'paused'
        policy.paused = true
        policy.message = action === 'reset' ? '已复位，模型暂停' : '已接管，模型暂停'
      }
      state.oracle = false          // 后端收到手动动作会退出 oracle
      refresh()
    })
    .catch(console.error)
    .finally(() => {
      actInFlight = false
      const next = actNext
      actNext = null
      if (next) sendAct(next)
    })
}

const KEY_ACTION = {
  ArrowUp: 'forward',
  w: 'forward',
  W: 'forward',
  ArrowLeft: 'left',
  a: 'left',
  A: 'left',
  ArrowRight: 'right',
  d: 'right',
  D: 'right',
  ' ': 'stop',
  Spacebar: 'stop',
}

let repeatTimer = null
let activeKey = ''

function isTyping(target) {
  const tag = target?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable
}

function onKeyDown(event) {
  if (isTyping(event.target)) return
  const action = KEY_ACTION[event.key]
  if (!action) return
  event.preventDefault()
  if (event.repeat || activeKey === event.key) return
  activeKey = event.key
  pressed.add(action)
  act(action, true)
  clearInterval(repeatTimer)
  repeatTimer = setInterval(() => act(action), 160)
}

function onKeyUp(event) {
  if (!activeKey || event.key !== activeKey) return
  const action = KEY_ACTION[activeKey]
  pressed.delete(action)
  activeKey = ''
  clearInterval(repeatTimer)
  repeatTimer = null
}

let lastSeq = -1
let lastSeqAt = Date.now()
let pollTimer = null
let stuckTimer = null
// 断流重连：最多 3 次、每次退避一倍，超了就停下等用户点「重新连接画面」。
// 无限重连会让浏览器 6 条长连接被未结束的流占满，整页跟着卡死。
const STUCK_MS = 3000
const MAX_RECONNECT = 3
let reconnectCount = 0

onMounted(() => {
  loadDatasets()
  loadModels()
  loadGpus()
  refresh()
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  pollTimer = setInterval(refresh, 800)
  stuckTimer = setInterval(() => {
    if (state.status !== 'ready' || !state.session_id) return
    if (streamError.value) return          // 已经在错误态，等用户手动重连
    if (Date.now() - lastSeqAt <= STUCK_MS) return
    if (reconnectCount >= MAX_RECONNECT) {
      streamStuck.value = false
      streamError.value = '画面已停止更新：后端可能卡住或连接已断开。先点下面按钮重连；一直不行就重启后端进程'
      return
    }
    reconnectCount += 1
    streamStuck.value = true
    // 指数退避：第 n 次重连后要求连续 (STUCK_MS * n) 无帧才再试
    lastSeqAt = Date.now() + STUCK_MS * reconnectCount
    streamKey.value += 1
  }, 3000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  clearInterval(repeatTimer)
  clearInterval(pollTimer)
  clearInterval(stuckTimer)
})
</script>

<style scoped>
.sim-page {
  padding-bottom: 24px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.dataset-select {
  width: 220px;
}

.episode-select {
  width: 240px;
}

.gpu-select {
  width: 168px;
}

.policy-gpu-select {
  width: 118px;
}

.preview-strip {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 9px 16px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--nav-text-muted);
  overflow: hidden;
}

.preview-scene {
  font-family: var(--nav-font-mono);
  color: var(--nav-ink);
  font-weight: 600;
}

.preview-item b {
  font-family: var(--nav-font-mono);
  color: var(--nav-ink);
  font-weight: 600;
}

.preview-instruction {
  margin-left: auto;
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--nav-text-subtle);
}

.warn-bar {
  margin-bottom: 12px;
}

.empty-datasets {
  padding: 28px 0;
  margin-bottom: 12px;
}

.sim-main {
  display: block;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.panel-title {
  font-size: var(--nav-font-title);
  font-weight: 600;
  color: var(--nav-ink);
}

.panel-meta {
  font-family: var(--nav-font-mono);
  font-size: 11px;
  color: var(--nav-text-subtle);
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* 录制时长用等宽字体，数字跳动时不会把开关挤来挤去 */
.record-meta {
  white-space: nowrap;
}

.viewer-panel {
  padding: 14px 16px 16px;
}

.stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 340px;
  border-radius: var(--nav-radius-sm);
  border: 1px solid var(--nav-border);
  background: #0b0e13;
  overflow: hidden;
}

/* 画面是后端拼好的 1120×480（第一视角 + 俯视图），按原始比例铺满宽度 */
.stream {
  display: block;
  width: 100%;
  height: auto;
}

.stage-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stage-layer {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
  color: #9fb0c9;
  font-size: 13px;
  background: rgba(11, 14, 19, 0.92);
}

.stage-icon {
  font-size: 30px;
  color: var(--nav-accent);
}

.stage-hint {
  font-size: 11px;
  color: #6b7c95;
}

.stage-skeleton {
  width: min(420px, 80%);
  --el-skeleton-color: #1e2635;
  --el-skeleton-to-color: #2a3547;
}

.stage-error {
  color: #fca5a5;
}

.stage-error .stage-icon {
  color: #f87171;
}

/* 模型驾驶工具条：与手动控制条同一视觉语言，靠一条虚线分隔 */
.policy-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--nav-border);
}

.policy-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--nav-text);
}

.policy-select {
  width: 210px;
}

.policy-stats {
  font-family: var(--nav-font-mono);
  font-size: 11px;
  color: var(--nav-text-subtle);
}

.policy-error {
  font-size: 11px;
  color: var(--nav-danger);
}

/* 画面右上角的"模型驾驶中"标记：一眼看出这台狗现在是模型在开 */
.stage-badge {
  position: absolute;
  top: 10px;
  right: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(12, 16, 22, 0.72);
  border: 1px solid var(--nav-accent);
  font-family: var(--nav-font-mono);
  font-size: 11px;
  color: var(--nav-accent-strong);
}

.stage-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--nav-accent);
  animation: stage-pulse 1.2s ease-in-out infinite;
}

@keyframes stage-pulse {
  0%,
  100% {
    opacity: 0.35;
  }

  50% {
    opacity: 1;
  }
}

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.ctrl-btn {
  transition: transform 120ms ease, box-shadow 120ms ease;
}

.ctrl-btn kbd {
  margin-left: 7px;
  padding: 1px 5px;
  border: 1px solid currentColor;
  border-radius: 4px;
  font-family: var(--nav-font-mono);
  font-size: 10px;
  line-height: 1.5;
  opacity: 0.5;
}

.ctrl-btn.is-pressed {
  transform: translateY(1px);
  box-shadow: 0 0 0 2px var(--nav-accent-soft);
  border-color: var(--nav-accent);
  color: var(--nav-accent-strong);
}

.ctrl-stop {
  color: var(--nav-danger);
}

/* Oracle 驾驶中：按钮整体点亮，和"模型驾驶中"用同一套强调色 */
.ctrl-btn.is-oracle {
  border-color: var(--nav-accent);
  color: var(--nav-accent-strong);
  background: var(--nav-accent-soft);
}

.ctrl-hint {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--nav-text-subtle);
}

/* 读数条：画面上方的信息集中到画面下方一行，避免再开第二个面板 */
.readout-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--nav-border);
}

.readout {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 96px;
  padding: 8px 12px;
  border: 1px solid var(--nav-border);
  border-radius: var(--nav-radius-sm);
  background: var(--nav-bg-soft);
}

.readout-wide {
  flex: 1 1 220px;
  min-width: 0;
}

.readout-instruction {
  flex-basis: 320px;
}

.readout-label {
  font-size: 11px;
  color: var(--nav-text-subtle);
}

.readout-value {
  font-family: var(--nav-font-mono);
  font-size: 19px;
  font-weight: 600;
  color: var(--nav-ink);
  line-height: 1.1;
}

.readout-value i {
  margin-left: 3px;
  font-size: 11px;
  font-style: normal;
  font-weight: 400;
  color: var(--nav-text-subtle);
}

.readout-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--nav-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.state-message {
  margin: 10px 0 0;
  padding-top: 9px;
  border-top: 1px dashed var(--nav-border);
  font-size: 12px;
  color: var(--nav-warning);
}

@media (max-width: 1200px) {
  .preview-instruction {
    max-width: 100%;
    margin-left: 0;
  }

  .preview-strip {
    flex-wrap: wrap;
    gap: 10px;
  }
}
</style>
