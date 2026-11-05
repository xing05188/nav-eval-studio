<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">报告中心</h2>
        <div class="page-subtitle">按任务组合生成 Markdown 分析报告或 CSV 指标矩阵</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadReports">刷新</el-button>
        <el-tooltip content="访客角色仅可查看与下载报告" :disabled="canWrite">
          <span>
            <el-button type="primary" :icon="DocumentAdd" :disabled="!canWrite" @click="openGenerate">
              生成报告
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <div class="stats">
      <div class="stat panel">
        <div class="stat-label">报告总数</div>
        <div class="stat-value">{{ reports.length }}</div>
        <div class="stat-foot">Markdown 与 CSV 合计</div>
      </div>
      <div class="stat panel">
        <div class="stat-label">占用空间</div>
        <div class="stat-value">{{ formatBytes(totalSize) }}</div>
        <div class="stat-foot">存储于工作目录 reports/</div>
      </div>
      <div class="stat panel">
        <div class="stat-label">覆盖任务</div>
        <div class="stat-value">{{ coveredTasks }}</div>
        <div class="stat-foot">去重后的任务数</div>
      </div>
      <div class="stat panel">
        <div class="stat-label">最近生成</div>
        <div class="stat-value small">{{ reports[0]?.created_at || '—' }}</div>
        <div class="stat-foot">{{ reports[0]?.name || '暂无报告' }}</div>
      </div>
    </div>

    <section class="panel">
      <div class="panel-header filters">
        <el-select v-model="filterTask" placeholder="全部任务" clearable class="filter-task">
          <el-option
            v-for="item in candidates"
            :key="item.task_id"
            :value="item.task_id"
            :label="`${item.name} (#${item.task_id})`"
          />
        </el-select>
        <el-select v-model="filterFormat" placeholder="全部格式" clearable class="filter-format">
          <el-option label="Markdown" value="md" />
          <el-option label="CSV" value="csv" />
        </el-select>
        <span class="total">共 {{ filteredReports.length }} 份</span>
      </div>

      <el-table v-loading="loading" :data="filteredReports" empty-text="暂无报告，点击右上角生成">
        <el-table-column label="报告文件" min-width="300">
          <template #default="{ row }">
            <div class="report-cell">
              <div class="report-icon" :class="row.format">
                <el-icon :size="15"><Document /></el-icon>
              </div>
              <div class="report-meta">
                <div class="report-name" :class="{ missing: !row.exists }">{{ row.name }}</div>
                <div class="sub mono">{{ row.path || '—' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="覆盖任务" min-width="240">
          <template #default="{ row }">
            <div class="tag-row">
              <el-tag
                v-for="id in row.task_ids.slice(0, 3)"
                :key="id"
                size="small"
                effect="plain"
                type="info"
              >
                {{ taskName(id) }}
              </el-tag>
              <span v-if="row.task_ids.length > 3" class="sub">+{{ row.task_ids.length - 3 }}</span>
              <span v-if="!row.task_ids.length" class="sub">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="格式" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="row.format === 'csv' ? 'success' : 'primary'" effect="light">
              {{ row.format === 'csv' ? 'CSV' : 'Markdown' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100" align="right">
          <template #default="{ row }">
            <span class="mono">{{ formatBytes(row.size_bytes) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="生成时间" width="168">
          <template #default="{ row }">
            <span class="mono tiny muted">{{ row.created_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.exists ? 'success' : 'danger'" effect="plain">
              {{ row.exists ? '可用' : '文件缺失' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="!row.exists"
              :loading="downloading === row.id"
              @click="download(row)"
            >
              下载
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" title="生成分析报告" width="620px" :close-on-click-modal="false">
      <el-form label-width="94px">
        <el-form-item label="对比任务" required>
          <el-select
            v-model="form.task_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择已有指标结果的任务"
            class="full"
            @change="onTasksChange"
          >
            <el-option
              v-for="item in candidates"
              :key="item.task_id"
              :value="item.task_id"
              :label="`${item.name} (#${item.task_id})`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="基线任务">
          <el-select v-model="form.baseline_id" class="full" clearable placeholder="缺省取第一个任务">
            <el-option
              v-for="id in form.task_ids"
              :key="id"
              :value="id"
              :label="taskName(id)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="输出格式">
          <el-radio-group v-model="form.format">
            <el-radio-button value="md">Markdown</el-radio-button>
            <el-radio-button value="csv">CSV 指标矩阵</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.format === 'md'" label="报告章节">
          <el-checkbox-group v-model="form.include">
            <el-checkbox value="summary">结论摘要</el-checkbox>
            <el-checkbox value="metrics">指标矩阵</el-checkbox>
            <el-checkbox value="ablation">消融</el-checkbox>
            <el-checkbox value="significance">显著性</el-checkbox>
            <el-checkbox value="longhorizon">长时曲线</el-checkbox>
            <el-checkbox value="failures">失败归因</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item v-if="form.format === 'md'" label="失败样本">
          <el-input-number v-model="form.top_failures" :min="1" :max="50" />
          <span class="form-hint">条典型失败案例写入报告</span>
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="报告生成后会登记为产物，并立即下载到本地"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">生成并下载</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, DocumentAdd, Refresh } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'
import { formatBytes } from '@/utils/format'

const auth = useAuthStore()
const canWrite = computed(() => ['admin', 'operator'].includes(auth.role))

const reports = ref([])
const candidates = ref([])
const loading = ref(false)
const downloading = ref(null)
const submitting = ref(false)
const dialogVisible = ref(false)
const filterTask = ref(null)
const filterFormat = ref('')

const form = reactive({
  task_ids: [],
  baseline_id: null,
  format: 'md',
  include: ['summary', 'metrics', 'ablation', 'significance', 'longhorizon', 'failures'],
  top_failures: 10,
})

const taskMap = computed(() => new Map(candidates.value.map((item) => [item.task_id, item.name])))

function taskName(id) {
  return taskMap.value.get(id) || `#${id}`
}

const filteredReports = computed(() =>
  reports.value.filter((item) => {
    if (filterTask.value && !item.task_ids.includes(filterTask.value)) return false
    if (filterFormat.value && item.format !== filterFormat.value) return false
    return true
  }),
)

const totalSize = computed(() => reports.value.reduce((sum, item) => sum + (item.size_bytes || 0), 0))
const coveredTasks = computed(() => {
  const ids = new Set()
  reports.value.forEach((item) => item.task_ids.forEach((id) => ids.add(id)))
  return ids.size
})

async function loadReports() {
  loading.value = true
  try {
    const data = await api.reports()
    reports.value = data.items || []
  } finally {
    loading.value = false
  }
}

async function loadCandidates() {
  const data = await api.analysisTasks({ limit: 500 })
  candidates.value = data.items || []
}

function openGenerate() {
  if (!candidates.value.length) {
    ElMessage.warning('暂无已完成指标的任务，请先完成一次评测')
    return
  }
  form.task_ids = candidates.value.slice(0, 3).map((item) => item.task_id)
  form.baseline_id = form.task_ids[0] ?? null
  form.format = 'md'
  form.include = ['summary', 'metrics', 'ablation', 'significance', 'longhorizon', 'failures']
  form.top_failures = 10
  dialogVisible.value = true
}

function onTasksChange() {
  if (!form.task_ids.includes(form.baseline_id)) {
    form.baseline_id = form.task_ids[0] ?? null
  }
}

async function download(report) {
  if (report.exists === false) return
  downloading.value = report.id
  try {
    const blob = await api.downloadReport(report.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = report.name
    anchor.click()
    URL.revokeObjectURL(url)
  } finally {
    downloading.value = null
  }
}

async function submit() {
  if (!form.task_ids.length) {
    ElMessage.warning('请至少选择一个任务')
    return
  }
  submitting.value = true
  try {
    const artifact = await api.createReport({
      task_ids: form.task_ids,
      baseline_id: form.baseline_id,
      format: form.format,
      include: form.include,
      top_failures: form.top_failures,
    })
    dialogVisible.value = false
    await loadReports()
    await download(artifact)
    ElMessage.success(`已生成 ${artifact.name}`)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadReports(), loadCandidates()])
})
</script>

<style scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
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

.stat-value.small {
  font-size: 14px;
  line-height: 1.5;
}

.stat-foot {
  margin-top: 4px;
  font-size: 11px;
  color: #9aa8bc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filters {
  gap: 12px;
}

.filter-task {
  width: 240px;
}

.filter-format {
  width: 140px;
}

.total {
  margin-left: auto;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.report-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.report-icon {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--nav-accent-soft);
  color: var(--nav-accent);
  flex: 0 0 30px;
}

.report-icon.csv {
  background: #eafaf1;
  color: #16a34a;
}

.report-meta {
  min-width: 0;
}

.report-name {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-name.missing {
  color: #b91c1c;
  text-decoration: line-through;
}

.sub {
  color: var(--nav-text-muted);
  font-size: 12px;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.tiny {
  font-size: 11px;
}

.muted {
  color: var(--nav-text-muted);
}

.full {
  width: 100%;
}

.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--nav-text-muted);
}

@media (max-width: 1100px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
