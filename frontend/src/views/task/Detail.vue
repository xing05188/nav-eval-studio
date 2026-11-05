<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div class="title-block">
        <el-button link :icon="ArrowLeft" @click="router.push('/tasks')">返回任务列表</el-button>
        <div class="title-row">
          <h2 class="page-title">{{ task?.name || '评测任务' }}</h2>
          <el-tag v-if="task" size="small" round :type="statusMeta(task.status).type">
            {{ statusMeta(task.status).label }}
          </el-tag>
          <span v-if="live" class="live"><i />实时</span>
        </div>
        <div class="sub">
          {{ task?.dataset_name }} · {{ task?.split_name }} · {{ task?.model_name }}
        </div>
      </div>
      <div class="actions">
        <el-button v-if="task?.status === 'running'" type="warning" plain @click="control('pause')">
          暂停
        </el-button>
        <el-button v-if="task?.status === 'paused'" type="success" plain @click="control('resume')">
          恢复
        </el-button>
        <el-button
          v-if="['queued', 'running', 'paused'].includes(task?.status)"
          type="danger"
          plain
          @click="control('cancel')"
        >
          取消
        </el-button>
        <el-button
          v-if="['failed', 'canceled'].includes(task?.status)"
          type="warning"
          plain
          @click="control('retry')"
        >
          重跑失败项
        </el-button>
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="task?.error_msg"
      class="error"
      type="error"
      :closable="false"
      show-icon
      :title="task.error_msg"
    />

    <section class="panel progress-panel">
      <div class="progress-head">
        <div>
          <span class="label">执行进度</span>
          <span class="mono">{{ task?.progress_done ?? 0 }} / {{ task?.progress_total ?? 0 }}</span>
        </div>
        <div class="meta">
          <span>开始 {{ task?.started_at || '—' }}</span>
          <span>耗时 {{ task?.duration_s ? `${task.duration_s}s` : '—' }}</span>
          <span>GPU {{ task?.gpu_ids || '默认' }}</span>
        </div>
      </div>
      <el-progress
        :percentage="percent"
        :stroke-width="10"
        :status="progressStatus"
        :color="progressColor"
      />
    </section>

    <div class="metrics">
      <div v-for="item in metricCards" :key="item.label" class="metric panel">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value">{{ item.value }}</div>
        <div class="metric-foot">{{ item.foot }}</div>
      </div>
    </div>

    <div class="charts">
      <section class="panel">
        <div class="panel-header">
          <span class="panel-title">单条推理时延（毫秒）</span>
          <span class="sub">按 episode 采样</span>
        </div>
        <div class="panel-body">
          <LineChart
            v-if="samples.length"
            :x-axis="sampleAxis"
            :series="latencySeries"
            y-name="ms"
            :height="200"
          />
          <el-empty v-else description="任务运行后显示" :image-size="56" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <span class="panel-title">显存峰值（MB）</span>
          <span class="sub">每条 episode 峰值</span>
        </div>
        <div class="panel-body">
          <LineChart
            v-if="samples.length"
            :x-axis="sampleAxis"
            :series="memorySeries"
            y-name="MB"
            :height="200"
          />
          <el-empty v-else description="任务运行后显示" :image-size="56" />
        </div>
      </section>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <el-tab-pane label="Episode 结果" name="episodes">
        <section class="panel">
          <div class="panel-header filters">
            <el-select v-model="epFilters.status" placeholder="全部状态" clearable style="width: 130px" @change="reloadEpisodes">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="待执行" value="pending" />
            </el-select>
            <el-select v-model="epFilters.reason" placeholder="失败原因" clearable style="width: 150px" @change="reloadEpisodes">
              <el-option
                v-for="item in task?.reasons || []"
                :key="item.reason"
                :label="`${reasonLabel(item.reason)}（${item.count}）`"
                :value="item.reason"
              />
            </el-select>
            <el-input
              v-model="epFilters.q"
              placeholder="搜索指令"
              clearable
              style="width: 200px"
              :prefix-icon="Search"
              @keyup.enter="reloadEpisodes"
              @clear="reloadEpisodes"
            />
            <el-button :icon="Search" @click="reloadEpisodes">查询</el-button>
            <span class="total">共 {{ episodeTotal }} 条</span>
          </div>

          <el-table :data="episodes" size="default" empty-text="暂无结果">
            <el-table-column prop="episode_key" label="编号" width="90" />
            <el-table-column prop="scene_id" label="场景" width="140" show-overflow-tooltip />
            <el-table-column prop="instruction" label="指令" min-width="280" show-overflow-tooltip />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.success ? 'success' : 'danger'" effect="plain">
                  {{ row.success ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="SPL" width="80">
              <template #default="{ row }">
                <span class="mono">{{ row.spl?.toFixed(3) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="NE" width="80">
              <template #default="{ row }">
                <span class="mono">{{ row.ne?.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="步数" width="76">
              <template #default="{ row }">
                <span class="mono">{{ row.steps }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时延" width="90">
              <template #default="{ row }">
                <span class="mono tiny">{{ row.latency_avg_ms }}ms</span>
              </template>
            </el-table-column>
            <el-table-column label="失败原因" width="120">
              <template #default="{ row }">
                <span v-if="row.failure_reason" class="reason">{{ reasonLabel(row.failure_reason) }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="132">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEpisode(row)">详情</el-button>
                <el-button
                  v-if="['success', 'failed'].includes(row.status)"
                  link
                  type="primary"
                  @click="openReplay(row)"
                >
                  回放
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="epPage"
              v-model:page-size="epPageSize"
              :total="episodeTotal"
              layout="prev, pager, next, total"
              @current-change="loadEpisodes"
            />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="运行日志" name="logs">
        <section class="panel">
          <div class="panel-header">
            <span class="panel-title">run.log</span>
            <div class="log-actions">
              <el-switch v-model="followLog" size="small" active-text="跟随" />
              <el-button size="small" :icon="Refresh" @click="loadLogs">刷新</el-button>
            </div>
          </div>
          <pre ref="logBox" class="log-box">{{ logLines.join('\n') || '暂无日志' }}</pre>
        </section>
      </el-tab-pane>

      <el-tab-pane label="任务配置" name="config">
        <section class="panel">
          <div class="panel-header">
            <span class="panel-title">配置快照</span>
            <span class="sub">创建时固化，不受模板变更影响</span>
          </div>
          <pre class="config-box">{{ configText }}</pre>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawerVisible" title="Episode 详情" size="560px">
      <div v-if="activeEpisode" class="drawer">
        <div class="group-title">导航指令</div>
        <p class="instruction">{{ activeEpisode.instruction }}</p>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="编号">{{ activeEpisode.episode_key }}</el-descriptions-item>
          <el-descriptions-item label="场景">{{ activeEpisode.scene_id }}</el-descriptions-item>
          <el-descriptions-item label="结果">
            {{ activeEpisode.success ? '成功' : '失败' }}
          </el-descriptions-item>
          <el-descriptions-item label="失败原因">
            {{ activeEpisode.failure_reason ? reasonLabel(activeEpisode.failure_reason) : '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="SPL">{{ activeEpisode.spl }}</el-descriptions-item>
          <el-descriptions-item label="NE">{{ activeEpisode.ne }}</el-descriptions-item>
          <el-descriptions-item label="nDTW">{{ activeEpisode.ndtw }}</el-descriptions-item>
          <el-descriptions-item label="TL">{{ activeEpisode.tl }} m</el-descriptions-item>
          <el-descriptions-item label="步数">{{ activeEpisode.steps }}</el-descriptions-item>
          <el-descriptions-item label="平均时延">{{ activeEpisode.latency_avg_ms }} ms</el-descriptions-item>
        </el-descriptions>

        <el-alert
          class="replay-tip"
          type="info"
          :closable="false"
          show-icon
          title="轨迹与记忆窗口回放将在 M5 里程碑开放"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import LineChart from '@/components/LineChart.vue'
import { formatPercent, formatNumber } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.id)

const task = ref(null)
const loading = ref(false)
const samples = ref([])
const episodes = ref([])
const episodeTotal = ref(0)
const epPage = ref(1)
const epPageSize = ref(20)
const epFilters = reactive({ status: '', reason: '', q: '' })

const logLines = ref([])
const followLog = ref(true)
const logBox = ref(null)
const tab = ref('episodes')
const live = ref(false)

const drawerVisible = ref(false)
const activeEpisode = ref(null)

let source = null

const percent = computed(() => {
  if (!task.value?.progress_total) return 0
  return Math.min(100, Math.round((task.value.progress_done / task.value.progress_total) * 100))
})

const progressStatus = computed(() => {
  if (task.value?.status === 'succeeded') return 'success'
  if (task.value?.status === 'failed') return 'exception'
  return undefined
})

const progressColor = computed(() => {
  if (task.value?.status === 'paused') return '#d97706'
  if (task.value?.status === 'canceled') return '#94a3b8'
  return '#2f6fed'
})

const metricCards = computed(() => {
  const metrics = task.value?.metrics || {}
  return [
    { label: 'SR 成功率', value: formatPercent(metrics.sr), foot: `${metrics.episodes || 0} 条已完成` },
    { label: 'SPL 加权成功率', value: formatPercent(metrics.spl), foot: '路径效率' },
    { label: 'NE 导航误差', value: formatNumber(metrics.ne), foot: '米' },
    { label: 'nDTW', value: formatPercent(metrics.ndtw), foot: '轨迹相似度' },
    { label: '平均时延', value: metrics.latency_avg_ms ? `${metrics.latency_avg_ms}` : '—', foot: '毫秒/条' },
    { label: '显存峰值', value: metrics.gpu_mem_peak_mb ? `${metrics.gpu_mem_peak_mb}` : '—', foot: 'MB' },
  ]
})

const sampleAxis = computed(() => samples.value.map((item) => item.step))

const latencySeries = computed(() => [
  { name: '时延', data: samples.value.map((item) => item.latency_ms), color: '#2f6fed', area: true },
])

const memorySeries = computed(() => [
  { name: '显存', data: samples.value.map((item) => item.gpu_mem_mb), color: '#16a34a', area: true },
])

const configText = computed(() => JSON.stringify(task.value?.config || {}, null, 2))

function statusMeta(status) {
  const map = {
    queued: { label: '排队中', type: 'info' },
    preparing: { label: '准备中', type: 'warning' },
    running: { label: '运行中', type: 'primary' },
    paused: { label: '已暂停', type: 'warning' },
    succeeded: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    canceled: { label: '已取消', type: 'info' },
  }
  return map[status] || { label: status || '—', type: 'info' }
}

function reasonLabel(reason) {
  const map = {
    timeout: '超时',
    collision: '碰撞',
    off_track: '偏离轨迹',
    loop: '原地打转',
    stuck: '卡死',
    early_stop: '早停',
    goal_unreachable: '目标不可达',
    parse_error: '解析错误',
    oom: '显存不足',
    unknown: '未知',
  }
  return map[reason] || reason
}

async function loadTask() {
  task.value = await api.taskDetail(taskId)
}

async function loadSamples() {
  samples.value = await api.taskSamples(taskId, { limit: 300 })
}

async function loadEpisodes() {
  const data = await api.taskEpisodes(taskId, {
    page: epPage.value,
    page_size: epPageSize.value,
    status: epFilters.status || undefined,
    reason: epFilters.reason || undefined,
    q: epFilters.q || undefined,
  })
  episodes.value = data.items
  episodeTotal.value = data.total
}

function reloadEpisodes() {
  epPage.value = 1
  loadEpisodes()
}

async function loadLogs() {
  const data = await api.taskLogs(taskId, { lines: 400 })
  logLines.value = data.lines
  scrollLog()
}

function scrollLog() {
  if (!followLog.value) return
  nextTick(() => {
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  })
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([loadTask(), loadSamples(), loadEpisodes(), loadLogs()])
  } finally {
    loading.value = false
  }
}

function openEpisode(row) {
  activeEpisode.value = row
  drawerVisible.value = true
}

function openReplay(row) {
  router.push({ path: '/replay', query: { task_id: taskId, row_id: row.id } })
}

async function control(action) {
  const names = { pause: '暂停', resume: '恢复', cancel: '取消', retry: '重跑失败项' }
  if (action === 'cancel' || action === 'retry') {
    const confirmed = await ElMessageBox.confirm(`确认${names[action]}该任务？`, '操作确认', {
      type: 'warning',
    }).catch(() => false)
    if (!confirmed) return
  }
  try {
    const actionFn = {
      pause: api.pauseTask,
      resume: api.resumeTask,
      cancel: api.cancelTask,
      retry: api.retryTask,
    }[action]
    await actionFn(taskId)
    ElMessage.success(`${names[action]}指令已下发`)
    await loadTask()
  } catch {
    // 错误已提示
  }
}

function connectEvents() {
  if (!task.value || ['succeeded', 'failed', 'canceled'].includes(task.value.status)) return
  const token = localStorage.getItem('naveval_token') || ''
  source = new EventSource(`/api/tasks/${taskId}/events?token=${encodeURIComponent(token)}`)
  live.value = true

  source.addEventListener('progress', (event) => {
    const data = JSON.parse(event.data)
    if (task.value) {
      task.value.progress_done = data.done
      task.value.progress_total = data.total
    }
  })

  source.addEventListener('sample', (event) => {
    samples.value.push(JSON.parse(event.data))
    if (samples.value.length > 400) samples.value.splice(0, samples.value.length - 400)
  })

  source.addEventListener('log', (event) => {
    const data = JSON.parse(event.data)
    logLines.value.push(data.text)
    if (logLines.value.length > 800) logLines.value.splice(0, logLines.value.length - 800)
    scrollLog()
  })

  source.addEventListener('state', (event) => {
    const data = JSON.parse(event.data)
    if (task.value && data.status) task.value.status = data.status
  })

  source.addEventListener('done', async (event) => {
    const data = JSON.parse(event.data)
    closeEvents()
    await refreshAll()
    if (data.status === 'succeeded') ElMessage.success('评测任务已完成')
    if (data.status === 'failed') ElMessage.error('评测任务失败')
  })

  source.onerror = () => {
    closeEvents()
  }
}

function closeEvents() {
  if (source) {
    source.close()
    source = null
  }
  live.value = false
}

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([loadTask(), loadSamples(), loadEpisodes(), loadLogs()])
    connectEvents()
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(closeEvents)
</script>

<style scoped>
.title-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.live {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #16a34a;
}

.live i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #16a34a;
  animation: pulse 1.4s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.sub {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.actions {
  display: flex;
  gap: 8px;
}

.error {
  margin-bottom: 14px;
}

.progress-panel {
  padding: 16px 20px;
  margin-bottom: 14px;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.progress-head .label {
  margin-right: 10px;
  color: var(--nav-text);
  font-weight: 500;
}

.meta {
  display: flex;
  gap: 18px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}

.metric {
  padding: 14px 16px;
}

.metric-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.metric-value {
  font-size: 22px;
  font-weight: 600;
  margin: 4px 0 2px;
}

.metric-foot {
  font-size: 11px;
  color: #9aa5b5;
}

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 14px;
}

.tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.filters {
  gap: 10px;
}

.total {
  margin-left: auto;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
}

.reason {
  color: #dc2626;
  font-size: 12px;
}

.log-box {
  margin: 0;
  padding: 14px 18px;
  height: 420px;
  overflow: auto;
  background: #0b1220;
  color: #cbd5e1;
  font-size: 11.5px;
  line-height: 1.75;
  font-family: Consolas, 'SFMono-Regular', monospace;
  border-radius: 0 0 10px 10px;
}

.log-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-box {
  margin: 0;
  padding: 16px 18px;
  background: #f8fafc;
  font-size: 12px;
  line-height: 1.7;
  font-family: Consolas, monospace;
  border-radius: 0 0 10px 10px;
  max-height: 520px;
  overflow: auto;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.instruction {
  margin: 0 0 16px;
  line-height: 1.8;
}

.replay-tip {
  margin-top: 16px;
}

.mono {
  font-family: Consolas, monospace;
}

.tiny {
  font-size: 11px;
}

@media (max-width: 1400px) {
  .metrics {
    grid-template-columns: repeat(3, 1fr);
  }
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
