<template>
  <div class="obs">
    <div class="obs-head">
      <div class="tags">
        <el-tag :type="data.sensors.rgb ? 'success' : 'info'" size="small" effect="plain">
          RGB {{ data.counts.frames_rgb }} 帧
        </el-tag>
        <el-tag :type="data.sensors.depth ? 'success' : 'info'" size="small" effect="plain">
          深度 {{ data.counts.frames_depth }} 帧
        </el-tag>
        <el-tag :type="data.sensors.pose ? 'success' : 'info'" size="small" effect="plain">
          位姿 {{ data.counts.poses }} 条
        </el-tag>
      </div>
      <span class="source">
        数据来源：{{ data.source === 'observations' ? '观测目录' : '参考路径' }}
      </span>
    </div>

    <div class="obs-body">
      <div class="viewer">
        <img v-if="showFrame" :src="frameUrl" class="frame" alt="RGB 帧" />
        <div v-else class="placeholder">
          <el-icon :size="22"><Picture /></el-icon>
          <span>该 episode 未提供 RGB 帧</span>
          <small>可放置 observations/&lt;episode_id&gt;/rgb/ 后重新扫描</small>
        </div>
        <div class="pose-line mono">
          <span>x {{ poseText(activeItem.pose, 0) }}</span>
          <span>y {{ poseText(activeItem.pose, 1) }}</span>
          <span>z {{ poseText(activeItem.pose, 2) }}</span>
          <span class="muted">t={{ activeItem.t }}s</span>
        </div>
      </div>

      <div class="strip">
        <div
          v-for="item in data.timeline"
          :key="item.idx"
          class="cell"
          :class="{ active: item.idx === active }"
          @click="active = item.idx"
        >
          <span class="cell-idx">{{ item.idx }}</span>
          <span class="cell-tag" :class="{ on: item.rgb }">RGB</span>
        </div>
        <div v-if="!data.timeline.length" class="empty">无时间轴数据</div>
      </div>
    </div>

    <div v-if="data.source === 'reference_path'" class="note">
      当前数据集未提供观测帧与动作序列，时间轴由标注中的参考路径生成，仅用于检查指令与轨迹形态。
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  datasetId: { type: Number, required: true },
  rowId: { type: Number, required: true },
  data: { type: Object, required: true },
})

const active = ref(0)

watch(
  () => props.data,
  () => {
    active.value = 0
  },
)

const activeItem = computed(() => {
  const items = props.data.timeline || []
  return items[Math.min(active.value, items.length - 1)] || { idx: 0, t: 0, pose: [], rgb: false }
})

const showFrame = computed(() => Boolean(activeItem.value.rgb))

const frameUrl = computed(() => {
  const token = localStorage.getItem('naveval_token') || ''
  return `/api/datasets/${props.datasetId}/episodes/${props.rowId}/frame/${active.value}?kind=rgb&token=${encodeURIComponent(token)}`
})

function poseText(pose, index) {
  if (!pose || pose.length <= index) return '—'
  return Number(pose[index]).toFixed(2)
}
</script>

<style scoped>
.obs {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.obs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tags {
  display: flex;
  gap: 8px;
}

.source {
  font-size: 11px;
  color: var(--nav-text-muted);
}

.obs-body {
  display: grid;
  grid-template-columns: minmax(220px, 320px) 1fr;
  gap: 14px;
}

.viewer {
  border: 1px solid var(--nav-border);
  border-radius: 10px;
  overflow: hidden;
  background: #0f172a;
  display: flex;
  flex-direction: column;
}

.frame {
  width: 100%;
  height: 180px;
  object-fit: cover;
  display: block;
}

.placeholder {
  height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #94a3b8;
  font-size: 12px;
  background: #f8fafc;
}

.placeholder small {
  color: #b6c0cf;
  font-size: 10px;
}

.pose-line {
  display: flex;
  gap: 12px;
  padding: 8px 10px;
  background: #0b1220;
  color: #cbd5e1;
  font-size: 11px;
}

.pose-line .muted {
  color: #64748b;
}

.strip {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  padding: 10px;
  border: 1px solid var(--nav-border);
  border-radius: 10px;
  background: #fbfcfe;
  min-height: 64px;
}

.cell {
  flex: 0 0 46px;
  height: 42px;
  border: 1px solid #e2e8f4;
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cell:hover {
  border-color: #bcd0f5;
}

.cell.active {
  border-color: var(--nav-accent);
  background: var(--nav-accent-soft);
}

.cell-idx {
  font-size: 11px;
  color: #334155;
}

.cell-tag {
  font-size: 9px;
  color: #cbd5e1;
}

.cell-tag.on {
  color: #16a34a;
}

.empty {
  color: #9aa5b5;
  font-size: 12px;
}

.note {
  font-size: 11px;
  color: #8a97a8;
  background: #f8fafc;
  border: 1px dashed var(--nav-border);
  border-radius: 8px;
  padding: 8px 10px;
}
</style>
