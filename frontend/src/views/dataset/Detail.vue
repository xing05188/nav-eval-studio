<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div class="title-block">
        <el-button link :icon="ArrowLeft" @click="router.push('/datasets')">返回列表</el-button>
        <div class="title-row">
          <h2 class="page-title">{{ detail?.name || '数据集详情' }}</h2>
          <el-tag v-if="detail" size="small" effect="plain">{{ kindLabel(detail.kind) }}</el-tag>
          <el-tag v-if="detail" size="small" round :type="datasetStatus(detail.status).type">
            {{ datasetStatus(detail.status).label }}
          </el-tag>
          <span v-if="detail?.version" class="version mono">{{ detail.version }}</span>
        </div>
        <div class="path mono">{{ detail?.root_path }}</div>
      </div>
      <div class="actions">
        <el-button :loading="scanning" @click="scan">重新扫描</el-button>
        <el-button type="primary" :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <div class="stats">
      <div class="stat panel">
        <div class="stat-label">Episode</div>
        <div class="stat-value">{{ detail?.stats.episode_count ?? 0 }}</div>
      </div>
      <div class="stat panel">
        <div class="stat-label">场景数</div>
        <div class="stat-value">{{ detail?.stats.scene_count ?? 0 }}</div>
      </div>
      <div class="stat panel">
        <div class="stat-label">平均轨迹长度</div>
        <div class="stat-value">{{ formatNumber(detail?.stats.avg_traj_len) }} <small>m</small></div>
      </div>
      <div class="stat panel">
        <div class="stat-label">平均指令长度</div>
        <div class="stat-value">{{ formatNumber(detail?.stats.avg_instruction_len, 1) }} <small>词</small></div>
      </div>
      <div class="stat panel">
        <div class="stat-label">切分</div>
        <div class="stat-value">{{ detail?.stats.splits ?? 0 }}</div>
      </div>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <el-tab-pane label="Episode 浏览" name="episodes">
        <section class="panel">
          <div class="panel-header filters">
            <el-input
              v-model="epFilters.q"
              placeholder="搜索指令关键词"
              clearable
              style="width: 220px"
              :prefix-icon="Search"
              @keyup.enter="reloadEpisodes"
              @clear="reloadEpisodes"
            />
            <el-select
              v-model="epFilters.scene"
              placeholder="全部场景"
              clearable
              filterable
              style="width: 180px"
              @change="reloadEpisodes"
            >
              <el-option
                v-for="scene in detail?.scenes || []"
                :key="scene.scene_id"
                :label="`${scene.scene_id} (${scene.count})`"
                :value="scene.scene_id"
              />
            </el-select>
            <el-input-number
              v-model="epFilters.min_len"
              :min="0"
              :controls="false"
              placeholder="最小长度"
              style="width: 110px"
            />
            <span class="muted">—</span>
            <el-input-number
              v-model="epFilters.max_len"
              :min="0"
              :controls="false"
              placeholder="最大长度"
              style="width: 110px"
            />
            <el-button :icon="Search" @click="reloadEpisodes">查询</el-button>
            <span class="total">共 {{ episodeTotal }} 条</span>
          </div>

          <el-table
            :data="episodes"
            v-loading="episodeLoading"
            empty-text="没有匹配的 episode"
            :header-cell-style="{ fontSize: '12px' }"
            @row-click="openEpisode"
          >
            <el-table-column prop="episode_key" label="编号" width="100" />
            <el-table-column prop="scene_id" label="场景" width="150" show-overflow-tooltip />
            <el-table-column prop="instruction" label="指令" min-width="320" show-overflow-tooltip />
            <el-table-column label="词数" width="80">
              <template #default="{ row }">
                <span class="mono">{{ row.instruction_len }}</span>
              </template>
            </el-table-column>
            <el-table-column label="轨迹(m)" width="100">
              <template #default="{ row }">
                <span class="mono">{{ formatNumber(row.traj_len) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="深度" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.has_depth" size="small" type="success" effect="plain">有</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="openEpisode(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="epPage"
              v-model:page-size="epPageSize"
              :total="episodeTotal"
              layout="prev, pager, next, sizes, total"
              :page-sizes="[10, 20, 50, 100]"
              @current-change="loadEpisodes"
              @size-change="reloadEpisodes"
            />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="切分与导出" name="splits">
        <div class="split-grid">
          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">评测切分</span>
              <el-button type="primary" size="small" :icon="Plus" @click="openSplit">新建切分</el-button>
            </div>
            <el-table :data="detail?.splits || []" empty-text="尚未生成切分">
              <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ splitKindLabel(row.kind) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="episode_count" label="数量" width="80" />
              <el-table-column prop="seed" label="种子" width="76" />
              <el-table-column prop="created_at" label="创建时间" width="160">
                <template #default="{ row }">
                  <span class="mono sub">{{ row.created_at }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="140">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openExport(row)">导出</el-button>
                  <el-button link type="danger" @click="removeSplit(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">因果切片导出记录</span>
              <el-button size="small" :icon="Download" @click="openExport(null)">全量导出</el-button>
            </div>
            <el-table :data="detail?.exports || []" empty-text="暂无导出记录">
              <el-table-column prop="file" label="文件" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="mono sub">{{ row.file }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column prop="mtime" label="时间" width="164">
                <template #default="{ row }">
                  <span class="mono sub">{{ row.mtime }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button link type="primary" @click="download(row)">下载</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="质量校验" name="quality">
        <section class="panel">
          <div class="panel-header">
            <span class="panel-title">数据质量检查</span>
            <el-button type="primary" size="small" :loading="validating" @click="runValidate">
              执行校验
            </el-button>
          </div>
          <div class="panel-body">
            <el-empty
              v-if="!quality"
              description="尚未执行校验，点击右上角开始检查指令、轨迹与场景资产"
              :image-size="70"
            />
            <template v-else>
              <div class="quality-summary">
                <el-tag :type="quality.passed ? 'success' : 'warning'" effect="dark" size="large">
                  {{ quality.passed ? '通过' : '存在问题' }}
                </el-tag>
                <span class="muted">
                  检查 {{ quality.total_episodes }} 条 episode / {{ quality.scenes }} 个场景，
                  错误 {{ quality.summary.error }}，警告 {{ quality.summary.warn }}，
                  提示 {{ quality.summary.info }}
                </span>
                <span class="mono sub">{{ quality.checked_at }}</span>
              </div>
              <el-table :data="quality.issues" max-height="460" empty-text="未发现问题">
                <el-table-column label="级别" width="90">
                  <template #default="{ row }">
                    <el-tag
                      size="small"
                      :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'"
                      effect="plain"
                    >
                      {{ row.level === 'error' ? '错误' : row.level === 'warn' ? '警告' : '提示' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="label" label="检查项" width="140" />
                <el-table-column prop="episode_key" label="Episode" width="100">
                  <template #default="{ row }">
                    <span class="mono">{{ row.episode_key || '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="scene_id" label="场景" width="140" />
                <el-table-column prop="message" label="说明" min-width="260" show-overflow-tooltip />
              </el-table>
            </template>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="基本信息" name="info">
        <section class="panel">
          <div class="panel-body">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="数据集 ID">{{ detail?.id }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ kindLabel(detail?.kind) }}</el-descriptions-item>
              <el-descriptions-item label="版本">{{ detail?.version || '—' }}</el-descriptions-item>
              <el-descriptions-item label="指令语言">{{ detail?.instruction_lang }}</el-descriptions-item>
              <el-descriptions-item label="数据路径" :span="2">
                <span class="mono">{{ detail?.root_path }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="场景根目录" :span="2">
                <span class="mono">{{ detail?.meta.scene_root || '未设置' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="解析格式">
                {{ detail?.meta.format || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="最近扫描">{{ detail?.last_scan_at || '—' }}</el-descriptions-item>
              <el-descriptions-item label="备注" :span="2">{{ detail?.note || '—' }}</el-descriptions-item>
            </el-descriptions>

            <div v-if="detail?.meta.last_scan" class="scan-summary">
              <div class="group-title">最近一次扫描</div>
              <el-descriptions :column="4" border size="small">
                <el-descriptions-item label="解析">{{ detail.meta.last_scan.parsed }}</el-descriptions-item>
                <el-descriptions-item label="新增">{{ detail.meta.last_scan.inserted }}</el-descriptions-item>
                <el-descriptions-item label="更新">{{ detail.meta.last_scan.updated }}</el-descriptions-item>
                <el-descriptions-item label="移除">{{ detail.meta.last_scan.removed }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawerVisible" :title="`Episode ${activeEp?.episode_key || ''}`" size="780px">
      <div v-if="activeEp" class="drawer">
        <div class="instruction">
          <div class="group-title">导航指令</div>
          <p>{{ activeEp.instruction || '（空）' }}</p>
          <div class="chips">
            <el-tag size="small" effect="plain">{{ activeEp.scene_id }}</el-tag>
            <el-tag size="small" effect="plain">{{ activeEp.instruction_len }} 词</el-tag>
            <el-tag size="small" effect="plain">{{ formatNumber(activeEp.traj_len) }} m</el-tag>
          </div>
        </div>

        <div class="group-title">参考轨迹（俯视）</div>
        <TrajectoryCanvas
          :path="observation?.reference_path || []"
          :start="activeEp.start_pose"
          :goal="activeEp.goal_pose"
          :height="260"
        />

        <div class="group-title">多源观测时间轴</div>
        <ObservationTimeline
          v-if="observation"
          :dataset-id="detail.id"
          :row-id="activeEp.id"
          :data="observation"
        />
        <el-skeleton v-else :rows="4" animated />
      </div>
    </el-drawer>

    <el-dialog v-model="splitVisible" title="新建切分" width="520px">
      <el-form :model="splitForm" label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="splitForm.name" placeholder="例如 smoke-20 / subset-10pct" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="splitForm.kind" style="width: 100%">
            <el-option label="全集 full" value="full" />
            <el-option label="冒烟集 smoke" value="smoke" />
            <el-option label="分层子集 subset" value="subset" />
            <el-option label="自定义 custom" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="随机种子">
          <el-input-number v-model="splitForm.seed" :min="0" :max="99999" style="width: 160px" />
          <span class="form-tip">固定种子保证切分可复算</span>
        </el-form-item>
        <el-form-item v-if="splitForm.kind !== 'full'" label="数量">
          <el-input-number v-model="splitForm.count" :min="1" :max="20000" style="width: 160px" />
          <span class="form-tip">留空时：smoke 默认 20，subset 默认 10%</span>
        </el-form-item>
        <template v-if="splitForm.kind === 'custom'">
          <el-form-item label="场景前缀">
            <el-input v-model="splitForm.filters.scene_prefix" placeholder="可选" />
          </el-form-item>
          <el-form-item label="指令关键词">
            <el-input v-model="splitForm.filters.keyword" placeholder="可选" />
          </el-form-item>
          <el-form-item label="轨迹范围">
            <el-input-number v-model="splitForm.filters.min_traj_len" :min="0" :controls="false" style="width: 110px" />
            <span class="muted" style="margin: 0 8px">—</span>
            <el-input-number v-model="splitForm.filters.max_traj_len" :min="0" :controls="false" style="width: 110px" />
            <span class="form-tip">米</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="splitVisible = false">取消</el-button>
        <el-button type="primary" :loading="splitSaving" @click="submitSplit">生成切分</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="exportVisible" title="导出严格因果切片" width="560px">
      <el-form label-width="96px">
        <el-form-item label="切分">
          <el-select v-model="exportForm.split_id" clearable placeholder="不选则导出前 N 条" style="width: 100%">
            <el-option
              v-for="split in detail?.splits || []"
              :key="split.id"
              :label="`${split.name}（${split.episode_count} 条）`"
              :value="split.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="截断步数">
          <el-input-number v-model="exportForm.cutoff" :min="1" :max="5000" style="width: 160px" />
          <span class="form-tip">只保留 t &lt; cutoff 的观测</span>
        </el-form-item>
        <el-form-item label="最多导出">
          <el-input-number v-model="exportForm.limit" :min="1" :max="5000" style="width: 160px" />
          <span class="form-tip">条 episode</span>
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="导出时二次校验：若记录中出现 idx ≥ cutoff 的观测则整条丢弃，保证不含未来帧。"
      />
      <div v-if="exportResult" class="export-result">
        <el-tag type="success" effect="plain">因果校验通过</el-tag>
        <span class="mono sub">{{ exportResult.file }}</span>
        <span class="muted">共 {{ exportResult.episodes }} 条，未来帧 {{ exportResult.future_frames }}</span>
        <el-button link type="primary" @click="download(exportResult)">下载</el-button>
      </div>
      <template #footer>
        <el-button @click="exportVisible = false">关闭</el-button>
        <el-button type="primary" :loading="exporting" @click="submitExport">开始导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Download, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import TrajectoryCanvas from '@/components/TrajectoryCanvas.vue'
import ObservationTimeline from '@/components/ObservationTimeline.vue'
import {
  datasetStatus,
  formatBytes,
  formatNumber,
  kindLabel,
} from '@/utils/format'

const route = useRoute()
const router = useRouter()
const datasetId = Number(route.params.id)

const detail = ref(null)
const loading = ref(false)
const scanning = ref(false)
const tab = ref('episodes')

const episodes = ref([])
const episodeTotal = ref(0)
const episodeLoading = ref(false)
const epPage = ref(1)
const epPageSize = ref(20)
const epFilters = reactive({ q: '', scene: '', min_len: null, max_len: null })

const drawerVisible = ref(false)
const activeEp = ref(null)
const observation = ref(null)

const quality = ref(null)
const validating = ref(false)

const splitVisible = ref(false)
const splitSaving = ref(false)
const splitForm = reactive({
  name: '',
  kind: 'smoke',
  seed: 42,
  count: 20,
  filters: { scene_prefix: '', keyword: '', min_traj_len: null, max_traj_len: null },
})

const exportVisible = ref(false)
const exporting = ref(false)
const exportResult = ref(null)
const exportForm = reactive({ split_id: null, cutoff: 20, limit: 100 })

const splitKindLabel = (kind) =>
  ({ full: '全集', smoke: '冒烟集', subset: '分层子集', custom: '自定义' })[kind] || kind

async function loadDetail() {
  loading.value = true
  try {
    detail.value = await api.datasetDetail(datasetId)
  } finally {
    loading.value = false
  }
}

async function loadEpisodes() {
  episodeLoading.value = true
  try {
    const data = await api.episodes(datasetId, {
      page: epPage.value,
      page_size: epPageSize.value,
      q: epFilters.q || undefined,
      scene: epFilters.scene || undefined,
      min_len: epFilters.min_len ?? undefined,
      max_len: epFilters.max_len ?? undefined,
    })
    episodes.value = data.items
    episodeTotal.value = data.total
  } finally {
    episodeLoading.value = false
  }
}

function reloadEpisodes() {
  epPage.value = 1
  loadEpisodes()
}

async function openEpisode(row) {
  activeEp.value = row
  observation.value = null
  drawerVisible.value = true
  const [detailData, obsData] = await Promise.all([
    api.episode(datasetId, row.id),
    api.observations(datasetId, row.id),
  ])
  activeEp.value = { ...row, ...detailData }
  observation.value = obsData
}

async function scan() {
  scanning.value = true
  try {
    const result = await api.scanDataset(datasetId)
    ElMessage.success(`扫描完成：${result.episode_count} 条 episode`)
    await Promise.all([loadDetail(), reloadEpisodes()])
  } finally {
    scanning.value = false
  }
}

async function refreshAll() {
  await loadDetail()
  if (tab.value === 'episodes') await loadEpisodes()
}

async function runValidate() {
  validating.value = true
  try {
    quality.value = await api.validateDataset(datasetId)
    tab.value = 'quality'
    ElMessage.success(quality.value.passed ? '校验通过' : '校验完成，存在待处理问题')
  } finally {
    validating.value = false
  }
}

function openSplit() {
  Object.assign(splitForm, {
    name: '',
    kind: 'smoke',
    seed: 42,
    count: 20,
    filters: { scene_prefix: '', keyword: '', min_traj_len: null, max_traj_len: null },
  })
  splitVisible.value = true
}

async function submitSplit() {
  if (!splitForm.name.trim()) {
    ElMessage.warning('请输入切分名称')
    return
  }
  splitSaving.value = true
  try {
    const filters = {}
    if (splitForm.kind === 'custom') {
      Object.entries(splitForm.filters).forEach(([key, value]) => {
        if (value !== '' && value !== null && value !== undefined) filters[key] = value
      })
    }
    const split = await api.createSplit(datasetId, {
      name: splitForm.name.trim(),
      kind: splitForm.kind,
      seed: splitForm.seed,
      count: splitForm.kind === 'full' ? undefined : splitForm.count || undefined,
      filters,
    })
    ElMessage.success(`已生成切分，共 ${split.episode_count} 条`)
    splitVisible.value = false
    await loadDetail()
  } finally {
    splitSaving.value = false
  }
}

async function removeSplit(row) {
  const confirmed = await ElMessageBox.confirm(
    `确认删除切分「${row.name}」？已引用该切分的任务不会受影响。`,
    '删除确认',
    { type: 'warning' },
  ).catch(() => false)
  if (!confirmed) return
  await api.deleteSplit(row.id)
  ElMessage.success('已删除')
  await loadDetail()
}

function openExport(split) {
  exportForm.split_id = split?.id || null
  exportResult.value = null
  exportVisible.value = true
}

async function submitExport() {
  exporting.value = true
  try {
    exportResult.value = await api.exportCausal(datasetId, {
      split_id: exportForm.split_id || undefined,
      cutoff: exportForm.cutoff,
      limit: exportForm.limit,
    })
    ElMessage.success('导出完成，因果性校验通过')
    await loadDetail()
  } finally {
    exporting.value = false
  }
}

async function download(row) {
  const filename = row.file || row.relative_path?.split('/').pop()
  const blob = await api.downloadExport(datasetId, filename)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await loadDetail()
  await loadEpisodes()
})
</script>

<style scoped>
.title-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.version {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.path {
  font-size: 11px;
  color: #94a3b8;
  word-break: break-all;
}

.actions {
  display: flex;
  gap: 10px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}

.stat {
  padding: 14px 16px;
}

.stat-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  margin-top: 4px;
}

.stat-value small {
  font-size: 12px;
  color: var(--nav-text-muted);
  font-weight: 400;
}

.tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.filters {
  gap: 10px;
  flex-wrap: wrap;
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

.split-grid {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 16px;
  align-items: start;
}

.quality-summary {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  margin: 16px 0 10px;
}

.drawer .group-title:first-child {
  margin-top: 0;
}

.instruction p {
  margin: 0 0 10px;
  line-height: 1.8;
  color: #1f2937;
}

.chips {
  display: flex;
  gap: 8px;
}

.form-tip {
  font-size: 11px;
  color: var(--nav-text-muted);
  margin-left: 10px;
}

.export-result {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 10px;
  background: #f6fbf7;
  border: 1px solid #d8efdf;
  border-radius: 8px;
  font-size: 12px;
}

.scan-summary {
  margin-top: 18px;
}

.sub {
  font-size: 12px;
  color: var(--nav-text-muted);
}

@media (max-width: 1320px) {
  .stats {
    grid-template-columns: repeat(3, 1fr);
  }
  .split-grid {
    grid-template-columns: 1fr;
  }
}
</style>
