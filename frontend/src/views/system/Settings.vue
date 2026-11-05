<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统设置</h2>
        <div class="page-subtitle">运行参数、工作目录与算力状态</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="reload">刷新</el-button>
        <el-button
          type="primary"
          :icon="Check"
          :loading="saving"
          :disabled="!auth.isAdmin"
          @click="save"
        >
          保存设置
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="settings-tabs">
      <el-tab-pane label="运行参数" name="params">
        <div class="grid-2">
          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">调度与存储</span>
              <el-tag v-if="!auth.isAdmin" size="small" type="warning" effect="plain">只读</el-tag>
            </div>
            <div class="panel-body">
              <el-form label-width="120px" class="settings-form">
                <el-form-item label="并发任务数">
                  <el-input-number v-model="form.max_parallel_tasks" :min="1" :max="8" :disabled="!auth.isAdmin" />
                  <span class="hint">同时执行的评测任务上限，保存后立即生效</span>
                </el-form-item>
                <el-form-item label="结果保留天数">
                  <el-input-number v-model="form.artifact_keep_days" :min="1" :max="3650" :disabled="!auth.isAdmin" />
                  <span class="hint">用于后续清理策略，默认 90 天</span>
                </el-form-item>
                <el-form-item label="回放帧间隔">
                  <el-input-number v-model="form.replay_frame_interval" :min="1" :max="10" :disabled="!auth.isAdmin" />
                  <span class="hint">回放工作台自动播放时的帧步长</span>
                </el-form-item>
                <el-form-item label="GPU 列表">
                  <el-input
                    v-model="form.gpu_ids"
                    placeholder="例如 0,1；留空表示使用默认卡"
                    :disabled="!auth.isAdmin"
                    class="gpu-input"
                  />
                  <span class="hint">逗号分隔的 GPU 编号，新建任务时可覆盖</span>
                </el-form-item>
                <el-form-item label="演示模式">
                  <el-switch v-model="form.demo_mode" :disabled="!auth.isAdmin" />
                  <span class="hint">开启后优先使用离线 Mock 结果，便于无 GPU 演示</span>
                </el-form-item>
                <el-form-item label="工作目录">
                  <el-input v-model="form.work_dir" disabled />
                  <span class="hint">由配置文件决定，修改后需重启服务</span>
                </el-form-item>
              </el-form>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">服务信息</span>
              <el-tag size="small" effect="plain" type="success">运行中</el-tag>
            </div>
            <div class="panel-body">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="软件版本">{{ status?.version || '—' }}</el-descriptions-item>
                <el-descriptions-item label="工作目录">
                  <span class="mono tiny">{{ status?.work_dir || form.work_dir || '—' }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="数据库大小">{{ status?.db_size_mb ?? '—' }} MB</el-descriptions-item>
                <el-descriptions-item label="工作目录占用">{{ status?.storage_used_mb ?? '—' }} MB</el-descriptions-item>
                <el-descriptions-item label="调度器">
                  并发 {{ form.max_parallel_tasks }} · 队列 {{ status?.counts?.queued ?? 0 }}
                </el-descriptions-item>
              </el-descriptions>

              <el-alert
                v-if="!auth.isAdmin"
                class="role-alert"
                type="warning"
                :closable="false"
                show-icon
                title="当前账号为只读角色，仅管理员可修改系统设置"
              />
              <el-alert
                v-else
                class="role-alert"
                type="info"
                :closable="false"
                show-icon
                title="并发额度保存后立即生效；工作目录等启动参数需修改配置文件并重启"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="系统状态" name="status">
        <div class="stats">
          <div class="stat panel">
            <div class="stat-label">磁盘可用</div>
            <div class="stat-value">{{ status?.disk_free_gb ?? '—' }} <small>GB</small></div>
            <el-progress :percentage="diskPercent" :stroke-width="5" :show-text="false" class="stat-bar" />
            <div class="stat-foot">共 {{ status?.disk_total_gb ?? '—' }} GB</div>
          </div>
          <div class="stat panel">
            <div class="stat-label">数据库</div>
            <div class="stat-value">{{ status?.db_size_mb ?? '—' }} <small>MB</small></div>
            <div class="stat-foot">SQLite · WAL 模式</div>
          </div>
          <div class="stat panel">
            <div class="stat-label">工作目录占用</div>
            <div class="stat-value">{{ status?.storage_used_mb ?? '—' }} <small>MB</small></div>
            <div class="stat-foot">runs / reports / logs</div>
          </div>
          <div class="stat panel">
            <div class="stat-label">任务队列</div>
            <div class="stat-value">{{ status?.counts?.queued ?? 0 }}</div>
            <div class="stat-foot">
              运行 {{ status?.counts?.running ?? 0 }} · 暂停 {{ status?.counts?.paused ?? 0 }}
            </div>
          </div>
        </div>

        <div class="grid-2">
          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">资产统计</span>
              <el-button link type="primary" :icon="Refresh" @click="loadStatus">刷新</el-button>
            </div>
            <div class="panel-body">
              <div class="count-grid">
                <div v-for="item in countItems" :key="item.label" class="count-item">
                  <div class="count-label">{{ item.label }}</div>
                  <div class="count-value">{{ item.value }}</div>
                </div>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">GPU 状态</span>
              <el-tag size="small" effect="plain" :type="status?.gpu?.available ? 'success' : 'info'">
                {{ status?.gpu?.available ? `${status.gpu.items.length} 卡` : '未检测' }}
              </el-tag>
            </div>
            <div class="panel-body">
              <el-table
                v-if="status?.gpu?.available"
                :data="status.gpu.items"
                size="small"
                empty-text="暂无 GPU"
              >
                <el-table-column prop="index" label="#" width="52" />
                <el-table-column prop="name" label="型号" min-width="160" show-overflow-tooltip />
                <el-table-column label="显存" width="150">
                  <template #default="{ row }">
                    <div class="gpu-mem">
                      <span class="mono tiny">{{ row.memory_used_mb }}/{{ row.memory_total_mb }} MB</span>
                      <el-progress
                        :percentage="gpuPercent(row)"
                        :stroke-width="4"
                        :show-text="false"
                        :color="gpuPercent(row) > 85 ? '#dc2626' : '#2f6fed'"
                      />
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="利用率" width="80" align="right">
                  <template #default="{ row }">
                    <span class="mono tiny">{{ row.utilization }}%</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty
                v-else
                :description="status?.gpu?.reason || '当前环境未检测到 GPU，Mock 模式仍可正常评测'"
                :image-size="56"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Refresh } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const tab = ref('params')
const loading = ref(false)
const saving = ref(false)
const status = ref(null)

const form = reactive({
  max_parallel_tasks: 2,
  artifact_keep_days: 90,
  replay_frame_interval: 1,
  gpu_ids: '',
  demo_mode: true,
  work_dir: '',
})

const diskPercent = computed(() => {
  if (!status.value?.disk_total_gb) return 0
  const used = status.value.disk_total_gb - status.value.disk_free_gb
  return Math.min(100, Math.max(0, Math.round((used / status.value.disk_total_gb) * 100)))
})

const countItems = computed(() => {
  const counts = status.value?.counts || {}
  return [
    { label: '数据集', value: counts.datasets ?? 0 },
    { label: 'Episode', value: counts.episodes ?? 0 },
    { label: '模型档案', value: counts.models ?? 0 },
    { label: '评测任务', value: counts.tasks ?? 0 },
    { label: '运行中', value: counts.running ?? 0 },
    { label: '失败任务', value: counts.failed ?? 0 },
  ]
})

function gpuPercent(gpu) {
  if (!gpu.memory_total_mb) return 0
  return Math.round((gpu.memory_used_mb / gpu.memory_total_mb) * 100)
}

function applySettings(rows) {
  const map = Object.fromEntries((rows || []).map((item) => [item.key, item.value]))
  form.max_parallel_tasks = Number(map.max_parallel_tasks || 2)
  form.artifact_keep_days = Number(map.artifact_keep_days || 90)
  form.replay_frame_interval = Number(map.replay_frame_interval || 1)
  form.gpu_ids = map.gpu_ids || ''
  form.demo_mode = (map.demo_mode ?? '1') === '1'
  form.work_dir = map.work_dir || ''
}

async function loadSettings() {
  const rows = await api.settings()
  applySettings(rows)
}

async function loadStatus() {
  status.value = await api.systemStatus()
}

async function reload() {
  loading.value = true
  try {
    await Promise.all([loadSettings(), loadStatus()])
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.updateSettings([
      { key: 'max_parallel_tasks', value: String(form.max_parallel_tasks) },
      { key: 'artifact_keep_days', value: String(form.artifact_keep_days) },
      { key: 'replay_frame_interval', value: String(form.replay_frame_interval) },
      { key: 'gpu_ids', value: form.gpu_ids },
      { key: 'demo_mode', value: form.demo_mode ? '1' : '0' },
    ])
    ElMessage.success('设置已保存')
    await loadSettings()
    await loadStatus()
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([loadSettings(), loadStatus()])
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.settings-tabs :deep(.el-tabs__item) {
  font-size: 13px;
}

.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.settings-form :deep(.el-form-item) {
  margin-bottom: 22px;
}

.settings-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
  gap: 6px 0;
}

.hint {
  width: 100%;
  font-size: 11px;
  color: #9aa8bc;
  line-height: 1.5;
}

.gpu-input {
  width: 260px;
}

.role-alert {
  margin-top: 16px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stat {
  padding: 14px 18px;
}

.stat-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.stat-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 600;
  color: #16233b;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.stat-value small {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.stat-bar {
  margin-top: 8px;
}

.stat-foot {
  margin-top: 4px;
  font-size: 11px;
  color: #9aa8bc;
}

.count-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.count-item {
  background: #f8faff;
  border: 1px solid #eef3fa;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}

.count-label {
  font-size: 11px;
  color: #93a2b8;
}

.count-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 600;
  color: #23324a;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.gpu-mem {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.tiny {
  font-size: 11px;
}

@media (max-width: 1200px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
