<template>
  <div>
    <div class="page-header">
      <div>
        <h2>运行看板</h2>
        <p>全平台数据资产、训练队列、在线部署与调用量的实时概览</p>
      </div>
      <div class="actions">
        <el-select v-model="days" size="default" style="width: 120px" @change="load">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="14" label="近 14 天" />
          <el-option :value="30" label="近 30 天" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <AsyncState :loading="loading && !summary" :error="error" :rows="8" @retry="load">
      <template v-if="summary">
        <div class="stat-grid">
          <div class="stat-card">
            <span class="label"><el-icon><Files /></el-icon> 数据集</span>
            <span class="value">{{ summary.dataset_count }}</span>
            <span class="sub">含版本切片与质量体检</span>
          </div>
          <div class="stat-card">
            <span class="label"><el-icon><Cpu /></el-icon> 训练任务</span>
            <span class="value">{{ summary.training_job_count }}</span>
            <span class="sub">
              成功率 {{ formatPercent(summary.job_success_rate) }} · 运行中 {{ summary.running_job_count }}
            </span>
          </div>
          <div class="stat-card">
            <span class="label"><el-icon><Box /></el-icon> 模型版本</span>
            <span class="value">{{ summary.model_count }}</span>
            <span class="sub">生产状态 {{ summary.production_model_count }}</span>
          </div>
          <div class="stat-card">
            <span class="label"><el-icon><Promotion /></el-icon> 在线部署</span>
            <span class="value">{{ summary.running_deployment_count }}</span>
            <span class="sub">共 {{ summary.deployment_count }} 个部署</span>
          </div>
          <div class="stat-card">
            <span class="label"><el-icon><Histogram /></el-icon> 今日调用</span>
            <span class="value">{{ formatNumber(summary.calls_today) }}</span>
            <span class="sub">
              错误率 {{ formatPercent(summary.error_rate_today) }} · 均延迟
              {{ Math.round(summary.avg_latency_ms_today || 0) }} ms
            </span>
          </div>
          <div class="stat-card">
            <span class="label"><el-icon><Coin /></el-icon> 今日 Token</span>
            <span class="value">{{ formatNumber(summary.tokens_today) }}</span>
            <span class="sub">按 API Key 记账，可审计到 trace</span>
          </div>
        </div>

        <div class="chart-row">
          <div class="card chart-card">
            <div class="card-title">
              <span>调用趋势（近 {{ days }} 天）</span>
              <span class="muted mono">请求 / Token / 错误</span>
            </div>
            <div v-if="bars.length" class="bars">
              <div v-for="(bar, index) in bars" :key="index" class="bar-col" :title="tooltip(index)">
                <div class="bar" :style="{ height: `${barHeight(index)}%` }" />
                <span class="bar-label">{{ shortDate(index) }}</span>
              </div>
            </div>
            <el-empty v-else :image-size="70" description="暂无调用数据，先用 API Key 发起一次推理" />
          </div>

          <div class="card side-card">
            <div class="card-title"><span>接入方式</span></div>
            <p class="muted side-desc">
              推理服务与 OpenAI SDK 完全兼容：把 <code>base_url</code> 指向本服务并用 API Key 鉴权即可。
            </p>
            <pre class="code-block">curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $MOPS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "ticket-clf",
       "messages": [
         {"role": "user",
          "content": "我要退款，订单一直没处理"}
       ]}'</pre>
            <router-link to="/deployments">
              <el-button size="small" type="primary" plain>去部署与在线调试 →</el-button>
            </router-link>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>最近训练任务</span>
            <router-link to="/training"><el-button text type="primary" size="small">全部任务 →</el-button></router-link>
          </div>
          <el-table :data="summary.recent_jobs" size="default" style="width: 100%">
            <el-table-column prop="name" label="任务" min-width="200" show-overflow-tooltip />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ taskTypeLabel(row.task_type) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="jobStatus(row.status).type" effect="light" size="small">
                  {{ jobStatus(row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="指标" width="150">
              <template #default="{ row }">
                <span v-if="row.metrics?.accuracy !== undefined" class="mono">
                  acc {{ formatPercent(row.metrics.accuracy, 2) }}
                </span>
                <span v-else-if="row.metrics?.chunk_count" class="mono muted">
                  {{ row.metrics.chunk_count }} chunks
                </span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="100">
              <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
            </el-table-column>
            <el-table-column label="提交时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.queued_at) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="60" description="还没有训练任务，去「训练任务」页发起第一个" />
            </template>
          </el-table>
        </div>

        <div class="card">
          <div class="card-title">
            <span>最近推理调用</span>
            <router-link to="/api-keys"><el-button text type="primary" size="small">调用日志 →</el-button></router-link>
          </div>
          <el-table :data="summary.recent_calls" size="default" style="width: 100%">
            <el-table-column label="Trace ID" width="190">
              <template #default="{ row }"><span class="mono">{{ truncate(row.trace_id, 16) }}</span></template>
            </el-table-column>
            <el-table-column prop="endpoint" label="接口" width="190" show-overflow-tooltip />
            <el-table-column prop="model_name" label="模型" width="140" show-overflow-tooltip />
            <el-table-column label="状态码" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status_code < 400 ? 'success' : 'danger'" size="small" effect="light">
                  {{ row.status_code }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="100">
              <template #default="{ row }">{{ row.latency_ms }} ms</template>
            </el-table-column>
            <el-table-column label="Token" width="110">
              <template #default="{ row }">{{ row.prompt_tokens + row.completion_tokens }}</template>
            </el-table-column>
            <el-table-column label="Key" width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ row.key_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty :image-size="60" description="暂无调用记录" />
            </template>
          </el-table>
        </div>
      </template>
    </AsyncState>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { dashboardApi } from '@/api'
import type { DashboardSummary, TimeseriesPoint } from '@/types'
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  jobStatus,
  taskTypeLabel,
  toBars,
  truncate,
} from '@/utils/format'

const loading = ref(false)
const error = ref('')
const summary = ref<DashboardSummary | null>(null)
const series = ref<TimeseriesPoint[]>([])
const days = ref(7)

const bars = computed(() => toBars(series.value.map((point) => point.requests), 14))
const maxRequests = computed(() => Math.max(1, ...bars.value))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [summaryData, timeseries] = await Promise.all([
      dashboardApi.summary(),
      dashboardApi.timeseries(days.value),
    ])
    summary.value = summaryData
    series.value = timeseries.items || []
  } catch (err) {
    error.value = (err as Error).message || '加载看板数据失败'
  } finally {
    loading.value = false
  }
}

function barHeight(index: number): number {
  return Math.max(4, Math.round((bars.value[index] / maxRequests.value) * 100))
}

function tooltip(index: number): string {
  const start = series.value.length - bars.value.length
  const point = series.value[Math.max(0, start + index)]
  if (!point) return ''
  return `${point.date}：${point.requests} 次请求 / ${point.tokens} tokens / ${point.errors} 错误`
}

function shortDate(index: number): string {
  const start = series.value.length - bars.value.length
  const point = series.value[Math.max(0, start + index)]
  return point ? point.date.slice(5) : ''
}

onMounted(load)
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.chart-row {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.chart-row .card + .card {
  margin-top: 0;
}

.chart-card,
.side-card {
  min-height: 250px;
}

.side-desc {
  font-size: 13px;
  line-height: 1.7;
  margin: 0 0 10px;
}

.side-card .code-block {
  max-height: 150px;
  margin-bottom: 12px;
}

@media (max-width: 1100px) {
  .chart-row {
    grid-template-columns: 1fr;
  }
}
</style>
