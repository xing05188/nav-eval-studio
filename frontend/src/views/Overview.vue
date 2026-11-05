<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">总览</h2>
        <div class="page-subtitle">评测资产、任务队列与运行环境状态</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="stats">
      <div v-for="item in stats" :key="item.label" class="stat-card panel">
        <div class="stat-icon" :style="{ background: item.bg, color: item.color }">
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-label">{{ item.label }}</div>
          <div class="stat-value">{{ item.value }}</div>
          <div class="stat-foot">{{ item.foot }}</div>
        </div>
      </div>
    </div>

    <div class="body-grid">
      <section class="panel">
        <div class="panel-header">
          <span class="panel-title">最近评测任务</span>
          <div class="queue-chips">
            <span class="chip"><i class="dot queued" />{{ queue.queued }} 排队</span>
            <span class="chip"><i class="dot running" />{{ queue.running }} 运行</span>
            <span class="chip"><i class="dot paused" />{{ queue.paused }} 暂停</span>
          </div>
        </div>

        <el-table
          :data="overview?.recent_tasks || []"
          v-loading="loading"
          size="default"
          empty-text="暂无评测任务，完成 M3 里程碑后可在此发起评测"
          :header-cell-style="{ fontSize: '12px' }"
        >
          <el-table-column prop="id" label="#" width="64" />
          <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="task-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="数据集 / 模型" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="task-sub">{{ row.dataset }}</div>
              <div class="task-sub muted">{{ row.model }}</div>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="120">
            <template #default="{ row }">
              <span class="mono small">{{ row.progress_done }}/{{ row.progress_total || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="SR" width="86">
            <template #default="{ row }">
              <span v-if="row.sr !== null && row.sr !== undefined">{{ formatPercent(row.sr) }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="104">
            <template #default="{ row }">
              <el-tag :type="statusMeta(row.status).type" size="small" effect="light" round>
                {{ statusMeta(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="queued_at" label="提交时间" width="164">
            <template #default="{ row }">
              <span class="mono small muted">{{ row.queued_at || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <div class="side">
        <section class="panel">
          <div class="panel-header">
            <span class="panel-title">存储与算力</span>
            <el-tag size="small" effect="plain" type="info">本机</el-tag>
          </div>
          <div class="panel-body">
            <div class="kv">
              <span>磁盘可用</span>
              <b>{{ status?.disk_free_gb ?? '—' }} GB / {{ status?.disk_total_gb ?? '—' }} GB</b>
            </div>
            <el-progress
              :percentage="diskPercent"
              :stroke-width="6"
              :show-text="false"
              color="#2f6fed"
            />
            <div class="kv" style="margin-top: 14px">
              <span>数据库</span>
              <b>{{ status?.db_size_mb ?? '—' }} MB</b>
            </div>
            <div class="kv">
              <span>工作目录</span>
              <b class="mono tiny">{{ status?.work_dir || '—' }}</b>
            </div>

            <el-divider />

            <div class="gpu-head">
              <span>GPU</span>
              <el-tag v-if="gpus.length" size="small" type="success" effect="plain">
                {{ gpus.length }} 卡
              </el-tag>
            </div>
            <div v-if="gpus.length" class="gpu-list">
              <div v-for="gpu in gpus" :key="gpu.index" class="gpu-item">
                <div class="flex-between">
                  <span class="gpu-name">#{{ gpu.index }} {{ gpu.name }}</span>
                  <span class="mono small">{{ gpu.memory_used_mb }}/{{ gpu.memory_total_mb }} MB</span>
                </div>
                <el-progress
                  :percentage="gpuPercent(gpu)"
                  :stroke-width="5"
                  :show-text="false"
                  color="#16a34a"
                />
              </div>
            </div>
            <el-empty
              v-else
              description="未检测到 NVIDIA GPU，离线演示模式仍可用"
              :image-size="50"
            />
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <span class="panel-title">评测流程</span>
          </div>
          <div class="panel-body steps">
            <div v-for="step in steps" :key="step.index" class="step">
              <span class="step-index">{{ step.index }}</span>
              <div class="step-main">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-desc">{{ step.desc }}</div>
              </div>
              <el-tag size="small" :type="step.type" effect="plain">{{ step.tag }}</el-tag>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '@/api'

const loading = ref(false)
const overview = ref(null)
const status = ref(null)

const queue = computed(() => overview.value?.queue || { queued: 0, running: 0, paused: 0 })
const gpus = computed(() => status.value?.gpu?.items || [])

const stats = computed(() => {
  const counts = overview.value?.counts || {}
  const rate = overview.value?.finish_rate
  return [
    {
      label: '数据集',
      value: counts.datasets ?? 0,
      foot: `${counts.episodes ?? 0} 条 episode`,
      icon: 'FolderOpened',
      bg: '#eaf1ff',
      color: '#2f6fed',
    },
    {
      label: '模型档案',
      value: counts.models ?? 0,
      foot: '含离线演示适配器',
      icon: 'Cpu',
      bg: '#ecfdf3',
      color: '#16a34a',
    },
    {
      label: '评测任务',
      value: counts.tasks ?? 0,
      foot: rate === null || rate === undefined ? '暂无完成任务' : `任务完成率 ${(rate * 100).toFixed(1)}%`,
      icon: 'VideoPlay',
      bg: '#fff7ed',
      color: '#d97706',
    },
    {
      label: '逐条结果',
      value: counts.episode_results ?? 0,
      foot: '任务级 episode 明细',
      icon: 'DataLine',
      bg: '#f5f3ff',
      color: '#7c3aed',
    },
  ]
})

const diskPercent = computed(() => {
  const total = status.value?.disk_total_gb || 0
  const free = status.value?.disk_free_gb || 0
  if (!total) return 0
  return Math.min(100, Math.round(((total - free) / total) * 100))
})

const steps = [
  { index: 1, title: '登记数据集与切分', desc: '扫描 episode、生成 smoke/subset', tag: 'M2', type: 'warning' },
  { index: 2, title: '创建并执行评测任务', desc: '配置快照、队列调度、实时监控', tag: 'M3', type: 'info' },
  { index: 3, title: '指标对比与失败诊断', desc: '消融矩阵、配对显著性、归因', tag: 'M4', type: 'info' },
  { index: 4, title: '轨迹回放与报告导出', desc: '四区联动回放、Markdown 报告', tag: 'M5', type: 'info' },
]

function gpuPercent(gpu) {
  if (!gpu.memory_total_mb) return 0
  return Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100)
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`
}

function statusMeta(value) {
  const map = {
    queued: { label: '排队中', type: 'info' },
    preparing: { label: '准备中', type: 'warning' },
    running: { label: '运行中', type: 'primary' },
    paused: { label: '已暂停', type: 'warning' },
    succeeded: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    canceled: { label: '已取消', type: 'info' },
  }
  return map[value] || { label: value || '未知', type: 'info' }
}

async function load() {
  loading.value = true
  try {
    const [overviewData, statusData] = await Promise.all([api.overview(), api.systemStatus()])
    overview.value = overviewData
    status.value = statusData
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  gap: 14px;
  padding: 18px;
  align-items: flex-start;
}

.stat-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 38px;
}

.stat-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.3;
  margin-top: 2px;
}

.stat-foot {
  font-size: 11px;
  color: var(--nav-text-subtle);
  margin-top: 4px;
}

.body-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

.queue-chips {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
  color: var(--nav-text-muted);
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: #f6f8fc;
  border: 1px solid var(--nav-border);
  border-radius: var(--nav-radius-xs);
  font-weight: 500;
  white-space: nowrap;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.dot.queued {
  background: #94a3b8;
}

.dot.running {
  background: #2f6fed;
}

.dot.paused {
  background: #d97706;
}

.task-name {
  font-weight: 500;
}

.task-sub {
  font-size: 12px;
  line-height: 1.5;
}

.muted {
  color: var(--nav-text-muted);
}

.small {
  font-size: 12px;
}

.tiny {
  font-size: 11px;
}

.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--nav-text-muted);
  margin-bottom: 8px;
  gap: 12px;
}

.kv b {
  color: var(--nav-text);
  font-weight: 500;
  text-align: right;
  word-break: break-all;
}

.gpu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--nav-text-muted);
  margin-bottom: 10px;
}

.gpu-item {
  margin-bottom: 10px;
}

.gpu-name {
  font-size: 12px;
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.step-index {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: #eef2fa;
  color: #64748b;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 20px;
  margin-top: 1px;
}

.step-main {
  flex: 1;
}

.step-title {
  font-size: 12.5px;
  font-weight: 500;
}

.step-desc {
  font-size: 11px;
  color: #9aa5b5;
  margin-top: 2px;
}

@media (max-width: 1280px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .body-grid {
    grid-template-columns: 1fr;
  }
}
</style>
