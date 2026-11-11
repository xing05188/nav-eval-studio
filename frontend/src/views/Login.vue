<template>
  <div class="login-page">
    <section class="brand-side">
      <div class="brand-top">
        <img class="brand-mark" src="/favicon.png" alt="NavEval Studio" />
        <span class="brand-name">NavEval Studio</span>
      </div>

      <div class="brand-body">
        <p class="eyebrow">用于 R2R-CE 与 RxR-CE 基准的评测、诊断与回放</p>
        <h1>码极客具身导航<br />评测与诊断软件</h1>
        <p class="lede">
          从数据准备到失败归因，把一次 VLN 评测变成可复现、可追溯的工程流程。
        </p>

        <figure class="chart">
          <svg
            class="track-svg"
            viewBox="0 0 560 226"
            role="img"
            aria-label="导航航迹示意图：从起点经三个路径点到达目标点"
          >
            <defs>
              <pattern id="login-grid" width="28" height="28" patternUnits="userSpaceOnUse">
                <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#1d3352" stroke-width="1" />
              </pattern>
            </defs>
            <rect x="0" y="0" width="560" height="226" fill="url(#login-grid)" opacity="0.6" />

            <g class="axis">
              <text x="14" y="20">Y / m</text>
              <text x="14" y="212">0</text>
              <text x="504" y="212">X / m</text>
            </g>

            <polyline
              class="track-path"
              points="46,186 158,138 272,150 386,96 496,58"
              fill="none"
              stroke="#48c9a9"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />

            <g class="nodes">
              <circle cx="46" cy="186" r="5" />
              <circle cx="158" cy="138" r="4" />
              <circle cx="272" cy="150" r="4" />
              <circle cx="386" cy="96" r="4" />
            </g>

            <g class="goal">
              <circle cx="496" cy="58" r="13" />
              <circle cx="496" cy="58" r="5" class="goal-core" />
            </g>

            <g class="labels">
              <text x="46" y="208">START</text>
              <text x="466" y="88">GOAL</text>
            </g>
          </svg>
          <figcaption class="chart-caption">
            <span><i class="key-line" /> 已走航迹</span>
            <span><i class="key-node" /> 路径节点</span>
            <span><i class="key-goal" /> 目标点</span>
            <span class="chart-id mono">PATH / 01</span>
          </figcaption>
        </figure>

        <ol class="flow" aria-label="评测流程">
          <li><span class="flow-no mono">01</span><span>数据与切分</span></li>
          <li><span class="flow-no mono">02</span><span>评测调度</span></li>
          <li><span class="flow-no mono">03</span><span>轨迹回放</span></li>
          <li><span class="flow-no mono">04</span><span>诊断分析</span></li>
        </ol>
      </div>

      <div class="brand-foot">V1.0.0，单机部署，无需外部服务</div>
    </section>

    <section class="form-side">
      <div class="form-card">
        <h2>登录工作台</h2>
        <p class="hint">使用账号口令进入评测与诊断环境</p>

        <el-form :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input
              v-model="form.username"
              size="large"
              placeholder="请输入用户名"
              :prefix-icon="User"
              autocomplete="username"
              aria-label="用户名"
            />
          </el-form-item>
          <el-form-item label="口令">
            <el-input
              v-model="form.password"
              type="password"
              size="large"
              show-password
              placeholder="请输入口令"
              :prefix-icon="Lock"
              autocomplete="current-password"
              aria-label="口令"
            />
          </el-form-item>

          <el-button
            type="primary"
            size="large"
            class="submit-btn"
            :loading="loading"
            native-type="submit"
          >
            进入系统
          </el-button>
        </el-form>

        <div class="tips">
          <div class="tips-title">内置演示账号</div>
          <div class="tips-row"><span>管理员</span><code>admin / admin123</code></div>
          <div class="tips-row"><span>算法工程师</span><code>operator / operator123</code></div>
          <div class="tips-row"><span>访客</span><code>viewer / viewer123</code></div>
        </div>
      </div>

      <div class="copyright">码极客具身导航评测与诊断软件 V1.0</div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/store/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: 'admin', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名与口令')
    return
  }
  loading.value = true
  try {
    await auth.login({ username: form.username.trim(), password: form.password })
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/overview'
    router.push(redirect)
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  --lg-night: #0b1a2e;
  --lg-chart: #10233c;
  --lg-grid: #1d3352;
  --lg-track: #48c9a9;
  --lg-text: #e6eefb;
  --lg-text-soft: #a9bdd8;
  --lg-text-dim: #9ab4d2;
  display: flex;
  min-height: 100vh;
  background: var(--nav-panel);
}

/* ---------------------------------------------------------------- 品牌侧 */

.brand-side {
  flex: 1 1 52%;
  min-width: 480px;
  background: var(--lg-night);
  border-right: 1px solid var(--lg-grid);
  color: var(--lg-text);
  display: grid;
  grid-template-rows: auto 1fr auto;
  align-items: center;
  gap: var(--nav-space-3);
  padding: var(--nav-space-4) 56px;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 11px;
  align-self: start;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: var(--nav-radius-sm);
  display: block;
  object-fit: contain;
  flex: 0 0 34px;
}

.brand-name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.brand-body {
  max-width: 520px;
}

.eyebrow {
  font-size: 12px;
  color: var(--lg-text-soft);
  margin: 0 0 14px;
}

h1 {
  font-size: 32px;
  line-height: 1.36;
  margin: 0 0 14px;
  font-weight: 600;
  letter-spacing: -0.3px;
}

.lede {
  color: var(--lg-text-soft);
  font-size: 13.5px;
  line-height: 1.8;
  max-width: 46ch;
  margin: 0;
}

.chart {
  max-width: 480px;
  margin: var(--nav-space-4) 0 var(--nav-space-3);
  padding: 10px 12px 0;
  border: 1px solid var(--lg-grid);
  border-radius: var(--nav-radius);
  background: var(--lg-chart);
}

.track-svg {
  display: block;
  width: 100%;
  height: auto;
}

.axis text,
.labels text {
  fill: var(--lg-text-dim);
  font-family: var(--nav-font-mono);
  font-size: 10px;
  letter-spacing: 0.4px;
}

.track-path {
  stroke: var(--lg-track);
  stroke-dasharray: 520;
  stroke-dashoffset: 520;
  animation: track-draw 1.4s var(--nav-ease) 0.15s forwards;
}

@keyframes track-draw {
  to { stroke-dashoffset: 0; }
}

.nodes circle {
  fill: var(--lg-chart);
  stroke: var(--lg-track);
  stroke-width: 2;
}

.goal circle {
  fill: none;
  stroke: var(--lg-track);
  stroke-width: 2;
  animation: goal-in 0.5s var(--nav-ease) 1.35s both;
}

.goal .goal-core {
  fill: var(--lg-track);
  stroke: none;
}

@keyframes goal-in {
  from { opacity: 0; transform: scale(0.6); transform-origin: 496px 58px; }
  to { opacity: 1; transform: scale(1); transform-origin: 496px 58px; }
}

.chart-caption {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-top: 8px;
  padding: 9px 2px;
  border-top: 1px solid var(--lg-grid);
  color: var(--lg-text-dim);
  font-size: 11px;
}

.chart-caption span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chart-caption i {
  display: inline-block;
  width: 12px;
  height: 2px;
  background: var(--lg-track);
}

.chart-caption .key-node {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 2px solid var(--lg-track);
  background: transparent;
}

.chart-caption .key-goal {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--lg-track);
  background: transparent;
}

.chart-id {
  margin-left: auto;
  font-size: 10px;
  letter-spacing: 0.6px;
}

.flow {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--lg-grid);
}

.flow li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 12px 10px 0 0;
  font-size: 12px;
  color: var(--lg-text-soft);
  white-space: nowrap;
}

.flow-no {
  font-size: 11px;
  color: var(--lg-track);
  letter-spacing: 0.5px;
}

.brand-foot {
  font-size: 11px;
  color: var(--lg-text-dim);
  align-self: end;
}

/* ---------------------------------------------------------------- 表单侧 */

.form-side {
  flex: 1 1 48%;
  min-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--nav-space-4) 56px;
  background: var(--nav-panel);
}

.form-card {
  width: 100%;
  max-width: 400px;
}

h2 {
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.3px;
  margin: 0 0 6px;
  color: var(--nav-ink);
}

.hint {
  color: var(--nav-text-muted);
  font-size: 13px;
  margin: 0 0 var(--nav-space-4);
}

.submit-btn {
  width: 100%;
  margin-top: 6px;
}

.tips {
  margin-top: var(--nav-space-4);
  padding-top: var(--nav-space-2);
  border-top: 1px solid var(--nav-border);
}

.tips-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--nav-text-muted);
  margin-bottom: 8px;
}

.tips-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--nav-text-muted);
  line-height: 2;
}

.tips-row code {
  font-family: var(--nav-font-mono);
  color: var(--nav-ink);
  white-space: nowrap;
}

.copyright {
  margin-top: var(--nav-space-4);
  font-size: 11px;
  color: var(--nav-text-subtle);
}

.mono {
  font-family: var(--nav-font-mono);
  font-variant-numeric: tabular-nums;
}

/* ---------------------------------------------------------------- 响应式 */

@media (max-width: 1100px) {
  .brand-side { padding: var(--nav-space-3) var(--nav-space-3) var(--nav-space-2); }
  .form-side { padding: var(--nav-space-3) var(--nav-space-3); }
  .flow li { font-size: 11px; }
}

@media (max-width: 960px) {
  .login-page { flex-direction: column; }

  .brand-side {
    flex: none;
    min-width: 0;
    width: 100%;
    padding: 18px 24px;
    border-right: none;
    border-bottom: 1px solid var(--lg-grid);
    gap: 12px;
  }

  h1 { font-size: 20px; margin-bottom: 8px; }
  .eyebrow { margin-bottom: 8px; }
  .lede, .chart, .flow, .brand-foot { display: none; }

  .form-side {
    flex: 1;
    min-width: 0;
    padding: 36px 20px 40px;
  }
}

@media (max-width: 480px) {
  .brand-side { padding: 14px 16px; }
  .form-side { padding: 28px 16px 32px; }
  h1 { font-size: 18px; }
  .tips-row { flex-direction: column; gap: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .track-path { animation: none; stroke-dashoffset: 0; }
  .goal circle { animation: none; opacity: 1; }
}
</style>
