<template>
  <div ref="container" class="chart" :style="{ height: `${height}px` }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  xAxis: { type: Array, default: () => [] },
  series: { type: Array, default: () => [] },
  yName: { type: String, default: '' },
  height: { type: Number, default: 220 },
})

const container = ref(null)
let chart = null
let observer = null

function render() {
  if (!chart) return
  chart.setOption(
    {
      grid: { left: 52, right: 18, top: 30, bottom: 26 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.9)',
        borderWidth: 0,
        textStyle: { color: '#e2e8f0', fontSize: 11 },
      },
      legend: {
        show: props.series.length > 1,
        right: 0,
        top: 0,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: '#64748b', fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: props.xAxis,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e5eaf2' } },
        axisTick: { show: false },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        name: props.yName,
        nameTextStyle: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: '#eef2f8' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      series: props.series.map((item) => ({
        name: item.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: item.data,
        lineStyle: { width: 2, color: item.color },
        itemStyle: { color: item.color },
        areaStyle: item.area
          ? {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: `${item.color}33` },
                { offset: 1, color: `${item.color}00` },
              ]),
            }
          : undefined,
      })),
    },
    true,
  )
}

onMounted(() => {
  chart = echarts.init(container.value)
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(container.value)
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
  if (chart) chart.dispose()
  chart = null
})

watch(() => [props.xAxis, props.series], render, { deep: true })
</script>

<style scoped>
.chart {
  width: 100%;
}
</style>
