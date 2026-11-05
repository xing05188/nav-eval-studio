<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">备份库自动导入</h2>
        <div class="page-subtitle">同步数据集、场景资源、模型档案、历史评测结果与各类资料文件</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="reload">刷新</el-button>
        <el-button :icon="Search" :loading="previewing" @click="scan">扫描预览</el-button>
        <el-button
          type="primary"
          :icon="Download"
          :loading="importing"
          :disabled="!canWrite"
          @click="runImport"
        >
          立即导入
        </el-button>
      </div>
    </div>

    <el-alert
      class="intro"
      type="info"
      :closable="false"
      show-icon
      title="服务启动后会自动同步一次，之后按间隔监视目录变化做增量导入；已导入且未变化的对象会自动跳过。"
      :description="`绑定目录：${overview?.root || '—'}。大文件只登记路径与元信息，不复制到工作目录；训练/大规模轨迹数据仅登记，可在数据集页手动扫描。`"
    />

    <section class="panel">
      <div class="panel-header">
        <span class="panel-title">自动同步</span>
        <el-tag size="small" :type="auto?.enabled ? 'success' : 'info'" effect="plain">
          {{ auto?.enabled ? '已开启' : '已关闭' }}
        </el-tag>
        <el-tag v-if="auto?.running" size="small" type="warning" effect="plain">正在导入</el-tag>
      </div>
      <div class="panel-body">
        <el-form inline class="auto-form">
          <el-form-item label="自动导入">
            <el-switch v-model="autoForm.enabled" :disabled="!canWrite" />
          </el-form-item>
          <el-form-item label="轮询间隔">
            <el-input-number
              v-model="autoForm.interval_s"
              :min="10"
              :max="86400"
              :step="30"
              :disabled="!canWrite"
              controls-position="right"
            />
            <span class="unit">秒</span>
          </el-form-item>
          <el-form-item label="导入类别">
            <el-select
              v-model="form.sections"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :disabled="!canWrite"
              class="section-select"
            >
              <el-option
                v-for="item in sectionOptions"
                :key="item.key"
                :label="item.label"
                :value="item.key"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button :icon="Check" :disabled="!canWrite" :loading="savingAuto" @click="saveAuto">
              保存自动设置
            </el-button>
          </el-form-item>
        </el-form>

        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="上次同步">{{ auto?.last_run_at || '尚未执行' }}</el-descriptions-item>
          <el-descriptions-item label="下次检查">{{ auto?.next_run_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ reasonLabel(auto?.last_reason) }}</el-descriptions-item>
          <el-descriptions-item label="累计同步">{{ auto?.total_runs ?? 0 }} 次</el-descriptions-item>
          <el-descriptions-item label="最近新增">{{ auto?.last_summary?.created ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="最近更新">{{ auto?.last_summary?.updated ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="最近跳过">{{ auto?.last_summary?.skipped ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="最近失败">{{ auto?.last_summary?.failed ?? '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="auto?.last_error"
          class="inline-alert"
          type="error"
          :closable="false"
          show-icon
          :title="`最近一次同步出错：${auto.last_error}`"
        />
        <el-alert
          v-if="!canWrite"
          class="inline-alert"
          type="warning"
          :closable="false"
          show-icon
          title="当前账号为只读角色，仅管理员 / 算法工程师可修改设置与执行导入"
        />
      </div>
    </section>

    <div class="stats">
      <div v-for="item in sectionCards" :key="item.key" class="stat panel">
        <div class="stat-label">{{ item.label }}</div>
        <div class="stat-value">{{ item.found }}<small> 项</small></div>
        <div class="stat-foot">已索引 {{ item.indexed }} 条 · {{ item.description }}</div>
      </div>
    </div>

    <section class="panel">
      <div class="panel-header">
        <span class="panel-title">导入预览与结果</span>
        <div class="panel-actions">
          <el-checkbox v-model="form.force" size="small" @change="scan">
            覆盖已导入对象
          </el-checkbox>
          <span class="divider" />
          <span class="mono tiny">目录</span>
          <el-input v-model="form.root_path" size="small" class="root-input" placeholder="备份库根目录" />
        </div>
      </div>
      <div class="panel-body">
        <div v-if="preview" class="summary">
          <el-tag size="small">扫描 {{ preview.scanned }} 项</el-tag>
          <el-tag size="small" type="success">新增/待导入 {{ preview.created }}</el-tag>
          <el-tag size="small" type="warning">更新 {{ preview.updated }}</el-tag>
          <el-tag size="small" type="info">已存在 {{ preview.skipped }}</el-tag>
          <el-tag size="small" type="warning">未对齐 {{ preview.unmatched }}</el-tag>
          <el-tag size="small" type="danger">失败 {{ preview.failed }}</el-tag>
          <span class="mono tiny source">{{ preview.dry_run ? '预览模式' : '已执行' }} · {{ preview.duration_s }}s</span>
        </div>
        <div v-if="assetSummary.length" class="summary">
          <el-tag v-for="item in assetSummary" :key="item.key" size="small" effect="plain">
            {{ item.label }}：新增 {{ item.new }} / 变更 {{ item.changed }} / 未变 {{ item.unchanged }}
          </el-tag>
        </div>

        <el-table :data="preview?.items || []" height="340" size="small" empty-text="点击「扫描预览」查看待导入对象">
          <el-table-column label="类别" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="sectionType(row.section)" effect="plain">
                {{ sectionLabel(row.section) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
          <el-table-column label="源路径" min-width="230" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono tiny">{{ row.rel_path || row.path }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="100" align="right">
            <template #default="{ row }">
              <span class="mono tiny">{{ row.size_bytes ? formatBytes(row.size_bytes) : '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusMeta(row.status).type">
                {{ statusMeta(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ 'error-text': row.status === 'failed' }">{{ row.message }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <span class="panel-title">资料索引</span>
        <el-button link type="primary" :icon="Refresh" @click="loadAssets">刷新</el-button>
      </div>
      <div class="panel-body">
        <div class="filters">
          <el-select v-model="assetFilters.section" clearable placeholder="全部类别" class="filter-control">
            <el-option
              v-for="item in sectionOptions"
              :key="item.key"
              :label="item.label"
              :value="item.key"
            />
          </el-select>
          <el-select v-model="assetFilters.status" clearable placeholder="全部状态" class="filter-control">
            <el-option label="已导入" value="imported" />
            <el-option label="已创建" value="created" />
            <el-option label="已更新" value="updated" />
            <el-option label="源文件缺失" value="missing" />
          </el-select>
          <el-input
            v-model="assetFilters.q"
            clearable
            placeholder="按文件名 / 路径检索"
            class="filter-search"
            @keyup.enter="searchAssets"
          />
          <el-button :icon="Search" @click="searchAssets">查询</el-button>
        </div>

        <el-table :data="assets" size="small" empty-text="尚未导入任何资料文件">
          <el-table-column label="类别" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="sectionType(row.section)">
                {{ sectionLabel(row.section) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="kind" label="类型" width="110" />
          <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip />
          <el-table-column label="相对路径" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono tiny">{{ row.rel_path }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="100" align="right">
            <template #default="{ row }">
              <span class="mono tiny">{{ formatBytes(row.size_bytes) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="mtime" label="修改时间" width="150" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusMeta(row.status).type">
                {{ statusMeta(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="assetPage"
            :page-size="assetPageSize"
            :total="assetTotal"
            layout="total, prev, pager, next"
            background
            @current-change="loadAssets"
          />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Download, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'
import { formatBytes } from '@/utils/format'

const auth = useAuthStore()
const canWrite = computed(() => auth.isAdmin || auth.role === 'operator')

const loading = ref(false)
const previewing = ref(false)
const importing = ref(false)
const savingAuto = ref(false)
const overview = ref(null)
const preview = ref(null)
const assets = ref([])
const assetTotal = ref(0)
const assetPage = ref(1)
const assetPageSize = 20
let timer = null

const form = reactive({ root_path: '', force: false, sections: [] })
const autoForm = reactive({ enabled: true, interval_s: 300 })
const assetFilters = reactive({ section: '', status: '', q: '' })

const auto = computed(() => overview.value?.auto || null)
const sectionOptions = computed(() =>
  (overview.value?.sections || []).map((item) => ({
    key: item.key,
    label: item.label,
    description: item.description,
    found: item.found,
    indexed: item.indexed,
  })),
)
const sectionCards = computed(() => sectionOptions.value)

const assetSummary = computed(() => {
  const counts = preview.value?.asset_counts || {}
  return Object.entries(counts)
    .filter(([, value]) => value.new || value.changed)
    .map(([key, value]) => ({
      key,
      label: sectionOptions.value.find((item) => item.key === key)?.label || key,
      new: value.new,
      changed: value.changed,
      unchanged: value.unchanged,
    }))
})

const SECTION_TYPES = {
  datasets: 'primary',
  scenes: 'success',
  models: 'warning',
  results: 'danger',
  assets: 'info',
}
const STATUS_META = {
  ready: { label: '待导入', type: 'warning' },
  created: { label: '已新增', type: 'success' },
  scanned: { label: '已解析', type: 'success' },
  registered: { label: '已登记', type: 'primary' },
  changed: { label: '待更新', type: 'warning' },
  updated: { label: '已更新', type: 'success' },
  imported: { label: '已导入', type: 'info' },
  skipped: { label: '已存在', type: 'info' },
  unmatched: { label: '未对齐', type: 'warning' },
  missing: { label: '源文件缺失', type: 'danger' },
  failed: { label: '失败', type: 'danger' },
}

function sectionLabel(key) {
  return sectionOptions.value.find((item) => item.key === key)?.label || key || '—'
}

function sectionType(key) {
  return SECTION_TYPES[key] || 'info'
}

function statusMeta(status) {
  return STATUS_META[status] || { label: status || '未知', type: 'info' }
}

function reasonLabel(reason) {
  return (
    { startup: '启动同步', change: '目录变化', config: '配置变更', manual: '手动触发' }[reason] ||
    (reason || '—')
  )
}

function applyAuto(data) {
  if (!data) return
  autoForm.enabled = Boolean(data.enabled)
  autoForm.interval_s = Number(data.interval_s || 300)
  if (!form.sections.length && data.sections?.length) {
    form.sections = [...data.sections]
  }
}

async function loadOverview(refreshOnly = false) {
  const params = form.root_path.trim() ? { root_path: form.root_path.trim() } : {}
  const data = await api.backupOverview(params)
  overview.value = data
  if (refreshOnly) return
  form.root_path = data.root || form.root_path
  applyAuto(data.auto)
  if (data.message) ElMessage.warning(data.message)
}

async function loadAssets() {
  const data = await api.backupAssets({
    section: assetFilters.section || undefined,
    status: assetFilters.status || undefined,
    q: assetFilters.q.trim() || undefined,
    page: assetPage.value,
    page_size: assetPageSize,
  })
  assets.value = data.items
  assetTotal.value = data.total
}

function importPayload(dryRun) {
  return {
    root_path: form.root_path.trim() || null,
    sections: form.sections,
    dry_run: dryRun,
    force: form.force,
  }
}

async function scan() {
  previewing.value = true
  try {
    preview.value = await api.backupImport(importPayload(true))
  } catch {
    preview.value = null
  } finally {
    previewing.value = false
  }
}

async function runImport() {
  if (!canWrite.value) {
    ElMessage.warning('当前角色为只读，无法执行导入')
    return
  }
  importing.value = true
  try {
    const result = await api.backupImport(importPayload(false))
    preview.value = result
    const text = `导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}，未对齐 ${result.unmatched}，失败 ${result.failed}`
    if (result.failed) ElMessage.warning(text)
    else ElMessage.success(text)
    await Promise.all([loadOverview(), loadAssets()])
  } catch {
    // 错误已由请求层提示
  } finally {
    importing.value = false
  }
}

async function saveAuto() {
  if (!canWrite.value) {
    ElMessage.warning('当前角色为只读，无法修改自动导入设置')
    return
  }
  savingAuto.value = true
  try {
    const data = await api.updateBackupAuto({
      enabled: autoForm.enabled,
      interval_s: autoForm.interval_s,
      root_path: form.root_path.trim() || undefined,
      sections: form.sections,
    })
    applyAuto(data)
    if (overview.value) overview.value.auto = data
    ElMessage.success('自动导入设置已保存，立即生效')
  } catch {
    // 错误已由请求层提示
  } finally {
    savingAuto.value = false
  }
}

function searchAssets() {
  assetPage.value = 1
  loadAssets()
}

async function reload() {
  loading.value = true
  try {
    await Promise.all([loadOverview(), loadAssets()])
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadOverview()
    await Promise.all([scan(), loadAssets()])
  } finally {
    loading.value = false
  }
  timer = setInterval(async () => {
    try {
      await loadOverview(true)
    } catch {
      // 后台刷新失败不打扰用户
    }
  }, 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 10px;
}

.intro {
  margin-bottom: 16px;
}

.panel {
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.divider {
  width: 1px;
  height: 16px;
  background: var(--nav-border);
}

.root-input {
  width: 280px;
}

.auto-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.unit {
  margin-left: 6px;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.section-select {
  width: 320px;
}

.inline-alert {
  margin-top: 14px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.stat {
  padding: 14px 16px;
}

.stat-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.stat-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
  color: #16233b;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.stat-value small {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.stat-foot {
  margin-top: 6px;
  font-size: 11px;
  color: #9aa8bc;
  line-height: 1.5;
  min-height: 32px;
}

.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.source {
  margin-left: auto;
  color: var(--nav-text-muted);
}

.filters {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.filter-control {
  width: 160px;
}

.filter-search {
  width: 280px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.tiny {
  font-size: 11px;
}

.error-text {
  color: #dc2626;
}

@media (max-width: 1400px) {
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .root-input {
    width: 200px;
  }
}
</style>
