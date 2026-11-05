<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">结果分析</h2>
        <div class="page-subtitle">指标对比、模态与记忆消融、显著性检验、长时曲线与失败归因</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="reload">刷新</el-button>
        <el-dropdown trigger="click" @command="exportReport">
          <el-button
            type="primary"
            :icon="Document"
            :loading="exporting"
            :disabled="!selected.length"
          >
            导出报告
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="md">Markdown 分析报告</el-dropdown-item>
              <el-dropdown-item command="csv">CSV 指标矩阵</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <section class="panel scope-panel">
      <div class="scope-row">
        <div class="field">
          <span class="field-label">对比任务</span>
          <el-select
            v-model="selected"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            placeholder="选择已有指标结果的任务"
            class="task-select"
            @change="onSelectionChange"
          >
            <el-option
              v-for="item in candidates"
              :key="item.task_id"
              :value="item.task_id"
              :label="`${item.name} (#${item.task_id})`"
            >
              <div class="option-row">
                <span>{{ item.name }}</span>
                <span class="option-meta">{{ item.modality }} · {{ item.memory_policy }}</span>
              </div>
            </el-option>
          </el-select>
        </div>
        <div class="field">
          <span class="field-label">基线</span>
          <el-select v-model="baseline" class="baseline-select" @change="loadCompare">
            <el-option
              v-for="id in selected"
              :key="id"
              :value="id"
              :label="taskLabel(id)"
            />
          </el-select>
        </div>
        <div class="scope-hint">
          已选 {{ selected.length }} 个任务，仅统计已完成 episode；差值与显著性均以基线为参照。
        </div>
      </div>
    </section>

    <section v-if="!candidates.length && !loading" class="panel empty-wrap">
      <el-empty description="暂无已完成指标的任务，请先在评测任务页面完成一次评测" />
    </section>

    <template v-else>
      <div v-if="rows.length" class="highlights">
        <div v-for="item in highlights" :key="item.label" class="highlight panel">
          <div class="highlight-label">{{ item.label }}</div>
          <div class="highlight-value">{{ item.value }}</div>
          <div class="highlight-task">{{ item.task }}</div>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="analysis-tabs" @tab-change="onTabChange">
        <el-tab-pane label="指标对比" name="compare" lazy>
          <section v-loading="loadingCompare" class="panel">
            <div class="panel-header">
              <span class="panel-title">多任务指标矩阵</span>
              <span class="sub">颜色表示相对基线的变化方向，绿色为更优</span>
            </div>
            <el-table
              v-if="rows.length"
              :data="rows"
              :row-class-name="rowClassName"
              empty-text="选择任务后显示"
            >
              <el-table-column label="任务" min-width="190" fixed="left">
                <template #default="{ row }">
                  <div class="task-cell">
                    <span class="task-name">{{ row.name }}</span>
                    <el-tag v-if="row.task_id === baseline" size="small" effect="plain" type="info">
                      基线
                    </el-tag>
                  </div>
                  <div class="sub">#{{ row.task_id }} · {{ row.dataset || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="配置" min-width="170">
                <template #default="{ row }">
                  <div class="sub">{{ row.modality }}</div>
                  <div class="sub muted">{{ row.memory_policy }}</div>
                </template>
              </el-table-column>
              <el-table-column label="Episodes" width="96" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ row.episodes }}</span>
                </template>
              </el-table-column>
              <el-table-column
                v-for="column in metricColumns"
                :key="column.key"
                :label="column.label"
                min-width="112"
                align="right"
              >
                <template #default="{ row }">
                  <div class="metric-cell">
                    <span class="metric-main">{{ metricText(column, row.values[column.key]) }}</span>
                    <span
                      v-if="row.task_id !== baseline"
                      class="metric-delta"
                      :class="deltaClass(column, getDelta(column.key, row.task_id))"
                    >
                      {{ deltaText(column, getDelta(column.key, row.task_id)) }}
                    </span>
                    <span v-else class="metric-delta flat">参照</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="panel-body">
              <el-empty description="请选择至少一个任务" :image-size="64" />
            </div>
          </section>
        </el-tab-pane>

        <el-tab-pane label="消融矩阵" name="ablation" lazy>
          <div v-loading="loadingAblation" class="grid-2">
            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">模态 × 记忆策略</span>
                <el-select v-model="heatMetric" size="small" class="heat-select">
                  <el-option
                    v-for="item in heatMetrics"
                    :key="item.key"
                    :label="item.label"
                    :value="item.key"
                  />
                </el-select>
              </div>
              <div class="panel-body">
                <BaseChart
                  v-if="ablationRows.length > 1"
                  :option="heatmapOption"
                  :height="320"
                />
                <el-empty
                  v-else
                  description="所选任务未覆盖两种以上「模态 × 记忆策略」组合"
                  :image-size="64"
                />
              </div>
            </section>

            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">组合明细</span>
                <span class="sub">同组任务取均值</span>
              </div>
              <el-table :data="ablationRows" empty-text="暂无消融组合">
                <el-table-column label="模态 / 记忆" min-width="180">
                  <template #default="{ row }">
                    <div>{{ row.modality }}</div>
                    <div class="sub muted">{{ row.memory_policy }}</div>
                  </template>
                </el-table-column>
                <el-table-column prop="tasks" label="任务" width="64" align="right" />
                <el-table-column label="SR" width="82" align="right">
                  <template #default="{ row }">
                    <span class="mono">{{ percent(row.values.sr) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="SPL" width="82" align="right">
                  <template #default="{ row }">
                    <span class="mono">{{ percent(row.values.spl) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="NE" width="80" align="right">
                  <template #default="{ row }">
                    <span class="mono">{{ row.values.ne.toFixed(2) }}m</span>
                  </template>
                </el-table-column>
                <el-table-column label="时延" width="88" align="right">
                  <template #default="{ row }">
                    <span class="mono tiny">{{ row.values.latency_avg_ms.toFixed(0) }}ms</span>
                  </template>
                </el-table-column>
              </el-table>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="显著性检验" name="significance" lazy>
          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">配对 Bootstrap 检验</span>
              <span class="sub">同一 episode 集合上重采样，95% 置信区间</span>
            </div>
            <div class="panel-body">
              <div class="sig-form">
                <div class="field">
                  <span class="field-label">任务 A</span>
                  <el-select v-model="sigA" class="sig-select" @change="sigResult = null">
                    <el-option v-for="id in selected" :key="id" :value="id" :label="taskLabel(id)" />
                  </el-select>
                </div>
                <span class="vs">VS</span>
                <div class="field">
                  <span class="field-label">任务 B</span>
                  <el-select v-model="sigB" class="sig-select" @change="sigResult = null">
                    <el-option v-for="id in selected" :key="id" :value="id" :label="taskLabel(id)" />
                  </el-select>
                </div>
                <div class="field">
                  <span class="field-label">重采样次数</span>
                  <el-select v-model="sigIterations" class="iter-select">
                    <el-option :value="500" label="500" />
                    <el-option :value="1000" label="1000" />
                    <el-option :value="2000" label="2000" />
                  </el-select>
                </div>
                <el-button type="primary" :loading="sigLoading" @click="runBootstrap">
                  运行检验
                </el-button>
              </div>

              <div v-if="sigResult" class="sig-result">
                <div class="sig-meta">
                  <el-tag size="small" effect="plain" type="info">
                    共同 episode {{ sigResult.episodes }} 条
                  </el-tag>
                  <el-tag size="small" effect="plain" type="info">
                    {{ sigResult.iterations }} 次重采样 · seed {{ sigResult.seed }}
                  </el-tag>
                </div>

                <div class="sig-cards">
                  <div v-for="item in sigRows" :key="item.key" class="sig-card">
                    <div class="sig-head">
                      <span class="sig-label">{{ item.label }}</span>
                      <el-tag
                        size="small"
                        effect="light"
                        :type="item.significant ? 'success' : 'info'"
                      >
                        {{ item.significant ? '显著' : '不显著' }}
                      </el-tag>
                    </div>
                    <div class="sig-delta" :class="item.delta > 0 ? 'up' : item.delta < 0 ? 'down' : 'flat'">
                      {{ item.deltaText }}
                    </div>
                    <div class="sig-grid">
                      <span>A 均值</span><b>{{ item.meanAText }}</b>
                      <span>B 均值</span><b>{{ item.meanBText }}</b>
                      <span>95% CI</span><b class="mono">{{ item.ciText }}</b>
                      <span>p 值</span><b class="mono">{{ item.pValueText }}</b>
                    </div>
                    <div class="sig-favor">更优：{{ item.favorText }}</div>
                  </div>
                </div>
              </div>

              <el-empty
                v-else
                description="选择两个任务后运行检验，得到指标差值、置信区间与 p 值"
                :image-size="64"
              />
            </div>
          </section>
        </el-tab-pane>

        <el-tab-pane label="长时性能" name="longhorizon" lazy>
          <section class="panel filters">
            <div class="field">
              <span class="field-label">任务</span>
              <el-select v-model="longTask" class="sig-select" @change="loadLong">
                <el-option v-for="id in selected" :key="id" :value="id" :label="taskLabel(id)" />
              </el-select>
            </div>
            <div class="field">
              <span class="field-label">步数分桶</span>
              <el-select v-model="longBuckets" class="iter-select" @change="loadLong">
                <el-option :value="4" label="4 组" />
                <el-option :value="5" label="5 组" />
                <el-option :value="6" label="6 组" />
                <el-option :value="8" label="8 组" />
              </el-select>
            </div>
            <span class="sub">按 episode 步数等宽分桶，观察成功率随交互长度的衰减</span>
          </section>

          <div v-loading="longLoading" class="grid-2">
            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">SR / SPL 随步数变化</span>
                <span class="sub">百分比</span>
              </div>
              <div class="panel-body">
                <LineChart
                  v-if="longAxis.length"
                  :x-axis="longAxis"
                  :series="longAccSeries"
                  y-name="%"
                  :height="240"
                />
                <el-empty v-else description="暂无分桶数据" :image-size="56" />
              </div>
            </section>

            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">NE 随步数变化</span>
                <span class="sub">米</span>
              </div>
              <div class="panel-body">
                <LineChart
                  v-if="longAxis.length"
                  :x-axis="longAxis"
                  :series="longNeSeries"
                  y-name="m"
                  :height="240"
                />
                <el-empty v-else description="暂无分桶数据" :image-size="56" />
              </div>
            </section>
          </div>

          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">分桶明细</span>
              <span class="sub" v-if="longData">{{ longData.task_name }}</span>
            </div>
            <el-table :data="longData?.buckets || []" empty-text="暂无数据">
              <el-table-column prop="label" label="步数区间" min-width="140" />
              <el-table-column prop="episodes" label="Episodes" width="100" align="right" />
              <el-table-column label="SR" width="100" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ percent(row.sr) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="SPL" width="100" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ percent(row.spl) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="NE" width="100" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ row.ne.toFixed(2) }} m</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="失败归因" name="failures" lazy>
          <section class="panel filters">
            <div class="field">
              <span class="field-label">任务</span>
              <el-select v-model="failTask" class="sig-select" @change="loadFailures">
                <el-option v-for="id in selected" :key="id" :value="id" :label="taskLabel(id)" />
              </el-select>
            </div>
            <div class="field">
              <span class="field-label">样本条数</span>
              <el-select v-model="failLimit" class="iter-select" @change="loadFailures">
                <el-option :value="10" label="10" />
                <el-option :value="20" label="20" />
                <el-option :value="50" label="50" />
              </el-select>
            </div>
            <span class="sub" v-if="failData">
              共 {{ failData.total_failed }} 条失败 episode
            </span>
          </section>

          <div v-loading="failLoading" class="grid-2">
            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">失败原因分布</span>
              </div>
              <div class="panel-body">
                <BaseChart
                  v-if="failData?.distribution?.length"
                  :option="failurePieOption"
                  :height="280"
                />
                <el-empty v-else description="该任务没有失败 episode" :image-size="56" />
              </div>
            </section>

            <section class="panel">
              <div class="panel-header">
                <span class="panel-title">归因统计</span>
                <span class="sub">按失败 episode 的最终原因汇总</span>
              </div>
              <el-table :data="failData?.distribution || []" empty-text="暂无失败">
                <el-table-column label="原因" min-width="140">
                  <template #default="{ row }">
                    <span class="reason-dot" />
                    {{ row.label }}
                  </template>
                </el-table-column>
                <el-table-column prop="count" label="数量" width="80" align="right" />
                <el-table-column label="占比" width="100" align="right">
                  <template #default="{ row }">
                    <span class="mono">{{ percent(row.ratio) }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </section>
          </div>

          <section class="panel">
            <div class="panel-header">
              <span class="panel-title">典型失败样本</span>
              <span class="sub">按导航误差 NE 降序</span>
            </div>
            <el-table :data="failData?.samples || []" empty-text="暂无失败样本">
              <el-table-column prop="episode_key" label="Episode" width="110" />
              <el-table-column prop="scene_id" label="场景" width="150" show-overflow-tooltip />
              <el-table-column prop="instruction" label="指令" min-width="280" show-overflow-tooltip />
              <el-table-column label="NE" width="86" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ row.ne.toFixed(2) }} m</span>
                </template>
              </el-table-column>
              <el-table-column label="SPL" width="86" align="right">
                <template #default="{ row }">
                  <span class="mono">{{ percent(row.spl) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="steps" label="步数" width="76" align="right" />
              <el-table-column label="原因" width="120">
                <template #default="{ row }">
                  <el-tag size="small" type="danger" effect="plain">
                    {{ failureLabel(row.failure_reason) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Document, Refresh } from '@element-plus/icons-vue'
import { api } from '@/api'
import BaseChart from '@/components/BaseChart.vue'
import LineChart from '@/components/LineChart.vue'
import { failureLabel } from '@/utils/format'

const candidates = ref([])
const selected = ref([])
const baseline = ref(null)
const activeTab = ref('compare')
const loading = ref(false)
const loadingCompare = ref(false)
const loadingAblation = ref(false)
const compareData = ref(null)
const ablationData = ref(null)
const exporting = ref(false)

const heatMetrics = [
  { key: 'sr', label: 'SR', percent: true, better: 'higher' },
  { key: 'spl', label: 'SPL', percent: true, better: 'higher' },
  { key: 'ne', label: 'NE', percent: false, better: 'lower' },
  { key: 'ndtw', label: 'nDTW', percent: true, better: 'higher' },
  { key: 'latency_avg_ms', label: '时延', percent: false, better: 'lower' },
]
const heatMetric = ref('sr')

const sigA = ref(null)
const sigB = ref(null)
const sigIterations = ref(1000)
const sigLoading = ref(false)
const sigResult = ref(null)

const longTask = ref(null)
const longBuckets = ref(5)
const longLoading = ref(false)
const longData = ref(null)

const failTask = ref(null)
const failLimit = ref(20)
const failLoading = ref(false)
const failData = ref(null)

const taskMap = computed(() => new Map(candidates.value.map((item) => [item.task_id, item])))
const metricColumns = computed(() => compareData.value?.columns || [])
const rows = computed(() => compareData.value?.rows || [])
const ablationRows = computed(() => ablationData.value?.rows || [])

function taskLabel(id) {
  const task = taskMap.value.get(id)
  return task ? `${task.name} (#${task.task_id})` : `#${id}`
}

function percent(value) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function metricText(column, value) {
  if (value === null || value === undefined) return '—'
  const number = Number(value)
  if (column.format === 'percent') return `${(number * 100).toFixed(1)}%`
  if (column.key === 'gpu_mem_peak_mb') return number.toFixed(0)
  return `${number.toFixed(2)}${column.unit || ''}`
}

function getDelta(key, taskId) {
  const bucket = compareData.value?.delta?.[key]
  if (!bucket) return 0
  return bucket[taskId] ?? bucket[String(taskId)] ?? 0
}

function deltaText(column, delta) {
  if (Math.abs(delta) < 1e-9) return '±0'
  if (column.format === 'percent') return `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)}pp`
  return `${delta > 0 ? '+' : ''}${delta.toFixed(2)}${column.unit || ''}`
}

function deltaClass(column, delta) {
  if (Math.abs(delta) < 1e-9) return 'flat'
  const better = column.better === 'higher' ? delta > 0 : delta < 0
  return better ? 'up' : 'down'
}

function rowClassName({ row }) {
  return row.task_id === baseline.value ? 'baseline-row' : ''
}

const highlights = computed(() => {
  if (!rows.value.length) return []
  const pick = (key, mode) =>
    rows.value.reduce((best, item) =>
      mode === 'max'
        ? (item.values[key] > best.values[key] ? item : best)
        : (item.values[key] < best.values[key] ? item : best),
    )
  const sr = pick('sr', 'max')
  const spl = pick('spl', 'max')
  const ne = pick('ne', 'min')
  const latency = pick('latency_avg_ms', 'min')
  return [
    { label: '最高 SR', value: percent(sr.values.sr), task: sr.name },
    { label: '最高 SPL', value: percent(spl.values.spl), task: spl.name },
    { label: '最低 NE', value: `${ne.values.ne.toFixed(2)} m`, task: ne.name },
    { label: '最低时延', value: `${latency.values.latency_avg_ms.toFixed(0)} ms`, task: latency.name },
  ]
})

const heatMeta = computed(
  () => heatMetrics.find((item) => item.key === heatMetric.value) || heatMetrics[0],
)

const heatmapOption = computed(() => {
  const data = ablationData.value
  if (!data || !data.modalities?.length) return {}
  const meta = heatMeta.value
  const points = []
  data.modalities.forEach((modality, y) => {
    data.policies.forEach((policy, x) => {
      const cell = data.matrix?.[modality]?.[policy]
      if (cell && cell[meta.key] !== undefined) {
        points.push([x, y, Number((cell[meta.key] * (meta.percent ? 100 : 1)).toFixed(2))])
      }
    })
  })
  const numbers = points.map((point) => point[2])
  let min = numbers.length ? Math.min(...numbers) : 0
  let max = numbers.length ? Math.max(...numbers) : 1
  if (min === max) max = min + 1
  const colors =
    meta.better === 'lower'
      ? ['#2f6fed', '#9dc0ff', '#eaf1ff']
      : ['#eaf1ff', '#9dc0ff', '#2f6fed']
  return {
    tooltip: {
      position: 'top',
      backgroundColor: 'rgba(15,23,42,0.9)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 11 },
      formatter: (params) =>
        `${data.modalities[params.value[1]]} × ${data.policies[params.value[0]]}<br/>` +
        `${meta.label}：<b>${params.value[2]}${meta.percent ? '%' : ''}</b>`,
    },
    grid: { left: 128, right: 74, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.policies,
      splitArea: { show: true },
      axisLine: { lineStyle: { color: '#e5eaf2' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: data.modalities,
      splitArea: { show: true },
      axisLine: { lineStyle: { color: '#e5eaf2' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 11 },
    },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: 'vertical',
      right: 0,
      top: 'center',
      itemWidth: 10,
      itemHeight: 90,
      textStyle: { fontSize: 10, color: '#64748b' },
      inRange: { color: colors },
    },
    series: [
      {
        type: 'heatmap',
        data: points,
        label: { show: true, fontSize: 11, color: '#1f2937' },
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(47,111,237,0.35)' } },
      },
    ],
  }
})

const sigRows = computed(() => {
  if (!sigResult.value) return []
  const labels = { success: 'SR 成功率', spl: 'SPL 加权成功率', ne: 'NE 导航误差' }
  return Object.entries(sigResult.value.metrics).map(([key, item]) => {
    const isPercent = key !== 'ne'
    const scale = isPercent ? 100 : 1
    const unit = isPercent ? '%' : 'm'
    return {
      key,
      label: labels[key],
      ...item,
      meanAText: `${(item.mean_a * scale).toFixed(2)}${unit}`,
      meanBText: `${(item.mean_b * scale).toFixed(2)}${unit}`,
      deltaText: `${item.delta > 0 ? '+' : ''}${(item.delta * scale).toFixed(2)}${isPercent ? 'pp' : 'm'}`,
      ciText: `[${(item.ci_low * scale).toFixed(2)}, ${(item.ci_high * scale).toFixed(2)}]${unit}`,
      pValueText: item.p_value.toFixed(4),
      favorText:
        item.favors === 'A'
          ? sigResult.value.task_a.name
          : item.favors === 'B'
            ? sigResult.value.task_b.name
            : '无差异',
    }
  })
})

const longAxis = computed(() => (longData.value?.buckets || []).map((item) => item.label))
const longAccSeries = computed(() => {
  const buckets = longData.value?.buckets || []
  return [
    { name: 'SR', data: buckets.map((item) => Number((item.sr * 100).toFixed(2))), color: '#2f6fed', area: true },
    { name: 'SPL', data: buckets.map((item) => Number((item.spl * 100).toFixed(2))), color: '#16a34a' },
  ]
})
const longNeSeries = computed(() => {
  const buckets = longData.value?.buckets || []
  return [
    { name: 'NE', data: buckets.map((item) => Number(item.ne.toFixed(2))), color: '#d97706', area: true },
  ]
})

const failurePieOption = computed(() => {
  const data = failData.value
  if (!data || !data.distribution?.length) return {}
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15,23,42,0.9)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 11 },
      formatter: '{b}<br/>{c} 条（{d}%）',
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: '#64748b' },
    },
    series: [
      {
        type: 'pie',
        radius: ['42%', '66%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}\n{d}%', fontSize: 11, color: '#475569' },
        data: data.distribution.map((item) => ({ name: item.label, value: item.count })),
      },
    ],
  }
})

async function loadCandidates() {
  const data = await api.analysisTasks({ limit: 200 })
  candidates.value = data.items || []
}

async function loadCompare() {
  if (!selected.value.length) {
    compareData.value = null
    return
  }
  if (!selected.value.includes(baseline.value)) {
    baseline.value = selected.value[0]
  }
  loadingCompare.value = true
  try {
    compareData.value = await api.analysisCompare({
      task_ids: selected.value.join(','),
      baseline_id: baseline.value,
    })
  } catch {
    compareData.value = null
  } finally {
    loadingCompare.value = false
  }
}

async function loadAblation() {
  if (!selected.value.length) {
    ablationData.value = null
    return
  }
  loadingAblation.value = true
  try {
    ablationData.value = await api.analysisAblation({ task_ids: selected.value.join(',') })
  } catch {
    ablationData.value = null
  } finally {
    loadingAblation.value = false
  }
}

async function loadLong() {
  if (!longTask.value) return
  longLoading.value = true
  try {
    longData.value = await api.analysisLongHorizon({
      task_id: longTask.value,
      buckets: longBuckets.value,
    })
  } catch {
    longData.value = null
  } finally {
    longLoading.value = false
  }
}

async function loadFailures() {
  if (!failTask.value) return
  failLoading.value = true
  try {
    failData.value = await api.analysisFailures({
      task_id: failTask.value,
      limit: failLimit.value,
    })
  } catch {
    failData.value = null
  } finally {
    failLoading.value = false
  }
}

function syncPickers() {
  if (!selected.value.includes(sigA.value)) sigA.value = selected.value[0] ?? null
  if (!selected.value.includes(sigB.value)) {
    sigB.value = selected.value.find((id) => id !== sigA.value) ?? selected.value[0] ?? null
  }
  if (!selected.value.includes(longTask.value)) longTask.value = selected.value[0] ?? null
  if (!selected.value.includes(failTask.value)) failTask.value = selected.value[0] ?? null
}

function onSelectionChange() {
  if (!selected.value.length) {
    compareData.value = null
    ablationData.value = null
    sigResult.value = null
    longData.value = null
    failData.value = null
    return
  }
  syncPickers()
  sigResult.value = null
  loadCompare()
  loadAblation()
  if (activeTab.value === 'longhorizon') loadLong()
  if (activeTab.value === 'failures') loadFailures()
}

function onTabChange(name) {
  if (name === 'longhorizon' && !longData.value) loadLong()
  if (name === 'failures' && !failData.value) loadFailures()
}

async function runBootstrap() {
  if (!sigA.value || !sigB.value) return
  if (sigA.value === sigB.value) {
    ElMessage.warning('请选择两个不同的任务')
    return
  }
  sigLoading.value = true
  try {
    sigResult.value = await api.analysisBootstrap({
      task_a: sigA.value,
      task_b: sigB.value,
      iterations: sigIterations.value,
    })
  } catch {
    sigResult.value = null
  } finally {
    sigLoading.value = false
  }
}

async function exportReport(format) {
  if (!selected.value.length) return
  exporting.value = true
  try {
    const artifact = await api.createReport({
      task_ids: selected.value,
      baseline_id: baseline.value,
      format,
      include: ['summary', 'metrics', 'ablation', 'significance', 'longhorizon', 'failures'],
      top_failures: 10,
    })
    const blob = await api.downloadReport(artifact.id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.name
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已生成 ${artifact.name}`)
  } finally {
    exporting.value = false
  }
}

async function reload() {
  loading.value = true
  try {
    await loadCandidates()
    const valid = selected.value.filter((id) => taskMap.value.has(id))
    selected.value = valid.length
      ? valid
      : candidates.value.slice(0, 3).map((item) => item.task_id)
    baseline.value = selected.value.includes(baseline.value) ? baseline.value : selected.value[0] ?? null
    syncPickers()
    await Promise.all([loadCompare(), loadAblation()])
    if (activeTab.value === 'longhorizon') await loadLong()
    if (activeTab.value === 'failures') await loadFailures()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadCandidates()
    selected.value = candidates.value.slice(0, 3).map((item) => item.task_id)
    baseline.value = selected.value[0] ?? null
    syncPickers()
    if (selected.value.length) {
      await Promise.all([loadCompare(), loadAblation()])
    }
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

.scope-panel {
  padding: 14px 18px;
  margin-bottom: 16px;
}

.scope-row {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}

.field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.field-label {
  font-size: 12px;
  color: var(--nav-text-muted);
  white-space: nowrap;
}

.task-select {
  width: 380px;
  max-width: 52vw;
}

.baseline-select {
  width: 210px;
}

.scope-hint {
  margin-left: auto;
  color: var(--nav-text-muted);
  font-size: 12px;
}

.option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.option-meta {
  color: #94a3b8;
  font-size: 11px;
}

.empty-wrap {
  padding: 40px 0;
}

.highlights {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.highlight {
  padding: 14px 18px;
}

.highlight-label {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.highlight-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
  color: #16233b;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.highlight-task {
  margin-top: 4px;
  font-size: 12px;
  color: #8794a8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.analysis-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.analysis-tabs :deep(.el-tabs__item) {
  font-size: 13px;
}

.task-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-name {
  font-weight: 500;
}

.sub {
  color: var(--nav-text-muted);
  font-size: 12px;
  margin-top: 2px;
}

.muted {
  color: #9aa6b8;
}

.metric-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.35;
}

.metric-main {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 13px;
  color: #1f2937;
}

.metric-delta {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
}

.metric-delta.up,
.sig-delta.up {
  color: var(--nav-success);
}

.metric-delta.down,
.sig-delta.down {
  color: var(--nav-danger);
}

.metric-delta.flat,
.sig-delta.flat {
  color: #9aa6b8;
}

:deep(.baseline-row) {
  background: #f7faff;
}

:deep(.baseline-row td) {
  background: #f7faff !important;
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.heat-select {
  width: 110px;
}

.filters {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 18px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.sig-form {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.sig-select {
  width: 220px;
}

.iter-select {
  width: 100px;
}

.vs {
  font-size: 11px;
  font-weight: 600;
  color: #9aa6b8;
  margin-top: 18px;
}

.sig-result {
  margin-top: 20px;
}

.sig-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.sig-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.sig-card {
  border: 1px solid var(--nav-border);
  border-radius: 10px;
  padding: 14px 16px;
  background: #fbfdff;
}

.sig-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sig-label {
  font-size: 13px;
  font-weight: 600;
}

.sig-delta {
  margin: 10px 0 12px;
  font-size: 24px;
  font-weight: 600;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.sig-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  row-gap: 5px;
  column-gap: 12px;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.sig-grid b {
  color: #1f2937;
  font-weight: 500;
  text-align: right;
}

.sig-favor {
  margin-top: 10px;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.reason-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--nav-accent);
  margin-right: 6px;
  vertical-align: 1px;
}

.tiny {
  font-size: 11px;
}

@media (max-width: 1280px) {
  .highlights {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .grid-2,
  .sig-cards {
    grid-template-columns: 1fr;
  }

  .task-select {
    width: 100%;
    max-width: none;
  }
}
</style>
