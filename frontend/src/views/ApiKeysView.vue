<template>
  <div>
    <div class="page-header">
      <div>
        <h2>API Key 与调用日志</h2>
        <p>Key 明文只在创建时返回一次，服务端只存 SHA-256 哈希；每次调用都做令牌桶限流、用量记账并落推理日志</p>
      </div>
      <div class="actions">
        <el-select v-model="days" style="width: 120px" @change="loadSummary">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="reloadAll">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建 Key</el-button>
      </div>
    </div>

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6">
        <div class="card stat-mini"><span>总请求</span><b>{{ formatNumber(summary?.total_requests) }}</b></div>
      </el-col>
      <el-col :span="6">
        <div class="card stat-mini"><span>总 Token</span><b>{{ formatNumber(summary?.total_tokens) }}</b></div>
      </el-col>
      <el-col :span="6">
        <div class="card stat-mini"><span>错误率</span><b>{{ formatPercent(summary?.error_rate, 2) }}</b></div>
      </el-col>
      <el-col :span="6">
        <div class="card stat-mini"><span>平均延迟</span><b>{{ summary?.avg_latency_ms ?? '—' }} ms</b></div>
      </el-col>
    </el-row>

    <AsyncState :loading="loading && !keys.length" :error="error" :rows="5" @retry="reloadAll">
      <div class="card">
        <div class="card-title">API Keys</div>
        <el-table :data="keys" style="width: 100%">
          <el-table-column label="名称" min-width="160">
            <template #default="{ row }">
              <b>{{ row.name }}</b>
              <div class="muted small">{{ row.scopes?.join(' · ') || '—' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="前缀" width="140">
            <template #default="{ row }"><code class="mono">{{ row.prefix }}…</code></template>
          </el-table-column>
          <el-table-column label="Token 配额" min-width="200">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.min(100, Math.round((row.quota_used_ratio || 0) * 100))"
                :status="row.quota_used_ratio >= 1 ? 'exception' : undefined"
                :stroke-width="10"
              />
              <div class="muted small mono quota-text">
                {{ formatNumber(row.tokens_used) }} / {{ formatNumber(row.token_quota) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="限流" width="130">
            <template #default="{ row }">
              <span class="mono">{{ row.rate_limit_per_min }}/min</span>
              <div class="muted small mono">burst {{ row.burst }}</div>
            </template>
          </el-table-column>
          <el-table-column label="请求数" width="90">
            <template #default="{ row }">{{ formatNumber(row.requests_used) }}</template>
          </el-table-column>
          <el-table-column label="最近使用" width="160">
            <template #default="{ row }">{{ formatDateTime(row.last_used_at) }}</template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="{ row }">
              <el-switch :model-value="row.active" @change="(value: string | number | boolean) => toggle(row, Boolean(value))" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openEdit(row)">配额设置</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有 API Key，点右上角「新建 Key」" />
          </template>
        </el-table>
      </div>

      <div class="card logs-card">
        <div class="card-title">
          推理调用日志
          <span class="muted small">（最近一次请求的 trace id、延迟、token 与错误详情都记在这里）</span>
        </div>
        <div class="filter-bar">
          <el-input
            v-model="logFilters.q"
            placeholder="搜索 trace id / 模型 / 提示词"
            clearable
            style="width: 260px"
            :prefix-icon="Search"
            @keyup.enter="searchLogs"
            @clear="searchLogs"
          />
          <el-select v-model="logFilters.endpoint" placeholder="接口" clearable style="width: 210px" @change="searchLogs">
            <el-option value="/v1/chat/completions" label="/v1/chat/completions" />
            <el-option value="/v1/embeddings" label="/v1/embeddings" />
            <el-option value="/v1/models" label="/v1/models" />
          </el-select>
          <el-select v-model="logFilters.status_code" placeholder="状态码" clearable style="width: 130px" @change="searchLogs">
            <el-option :value="200" label="200" />
            <el-option :value="401" label="401" />
            <el-option :value="429" label="429" />
            <el-option :value="500" label="500" />
          </el-select>
          <el-button @click="searchLogs">查询</el-button>
          <span class="muted">共 {{ logTotal }} 条</span>
        </div>

        <el-table :data="logs" size="small" style="width: 100%">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="log-detail">
                <div><span class="muted">Trace ID：</span><code class="mono">{{ row.trace_id }}</code></div>
                <div><span class="muted">Prompt：</span><span class="mono">{{ row.prompt_preview || '—' }}</span></div>
                <div><span class="muted">Response：</span><span class="mono">{{ row.response_preview || '—' }}</span></div>
                <div v-if="row.error"><span class="muted">Error：</span><span class="error-text">{{ row.error }}</span></div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="接口" width="190">
            <template #default="{ row }"><code class="mono">{{ row.endpoint }}</code></template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status_code < 400 ? 'success' : 'danger'" size="small" effect="light">
                {{ row.status_code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="模型 / 部署" min-width="170">
            <template #default="{ row }">
              <div>{{ row.model_name || '—' }}</div>
              <div class="muted small">{{ row.deployment_name || '—' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="Key" width="130" prop="key_name" />
          <el-table-column label="延迟" width="90">
            <template #default="{ row }"><span class="mono">{{ row.latency_ms }} ms</span></template>
          </el-table-column>
          <el-table-column label="Tokens" width="110">
            <template #default="{ row }">
              <span class="mono">{{ row.prompt_tokens }} + {{ row.completion_tokens }}</span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <template #empty><el-empty :image-size="60" description="还没有调用记录" /></template>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="logPage"
            :page-size="logSize"
            :total="logTotal"
            layout="prev, pager, next, total"
            background
            @current-change="loadLogs"
          />
        </div>
      </div>
    </AsyncState>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="formVisible" :title="editing ? '调整 Key 配额' : '新建 API Key'" width="500px">
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：客服机器人-生产" />
        </el-form-item>
        <el-form-item v-if="!editing" label="权限范围">
          <el-checkbox-group v-model="form.scopes">
            <el-checkbox value="chat" label="chat（对话）" />
            <el-checkbox value="embeddings" label="embeddings（向量化）" />
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="每分钟限额">
          <el-input-number v-model="form.rate_limit_per_min" :min="1" :max="100000" />
        </el-form-item>
        <el-form-item label="突发容量">
          <el-input-number v-model="form.burst" :min="1" :max="10000" />
        </el-form-item>
        <el-form-item label="Token 配额">
          <el-input-number v-model="form.token_quota" :min="1" :step="10000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">
          {{ editing ? '保存' : '创建并显示明文' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 明文只显示一次 -->
    <el-dialog v-model="plainVisible" title="API Key 创建成功（明文只显示这一次）" width="560px">
      <el-alert type="warning" :closable="false" show-icon title="请立刻复制保存：服务端只保存哈希，关闭后无法再次查看" />
      <code class="plain-key mono">{{ plainKey }}</code>
      <template #footer>
        <el-button type="primary" @click="copyPlainKey">复制到剪贴板</el-button>
        <el-button @click="plainVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { keyApi } from '@/api'
import type { ApiKeyInfo, InferenceLog, UsageSummary } from '@/types'
import { formatDateTime, formatNumber, formatPercent } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const days = ref(7)
const summary = ref<UsageSummary | null>(null)
const keys = ref<ApiKeyInfo[]>([])

const logs = ref<InferenceLog[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logSize = ref(10)
const logFilters = reactive({ q: '', endpoint: '', status_code: undefined as number | undefined })

const formVisible = ref(false)
const submitting = ref(false)
const editing = ref<ApiKeyInfo | null>(null)
const form = reactive({
  name: '',
  rate_limit_per_min: 60,
  burst: 10,
  token_quota: 200000,
  scopes: ['chat', 'embeddings'] as string[],
})

const plainVisible = ref(false)
const plainKey = ref('')

async function loadSummary(): Promise<void> {
  summary.value = await keyApi.usageSummary(days.value)
}

async function loadKeys(): Promise<void> {
  const result = await keyApi.list()
  keys.value = result.items
}

async function loadLogs(): Promise<void> {
  const result = await keyApi.usageLogs({
    page: logPage.value,
    size: logSize.value,
    q: logFilters.q || undefined,
    endpoint: logFilters.endpoint || undefined,
    status_code: logFilters.status_code,
  })
  logs.value = result.items
  logTotal.value = result.total
}

async function reloadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadSummary(), loadKeys(), loadLogs()])
  } catch (err) {
    error.value = (err as Error).message || '加载 API Key 数据失败'
  } finally {
    loading.value = false
  }
}

function searchLogs(): void {
  logPage.value = 1
  void loadLogs()
}

function openCreate(): void {
  editing.value = null
  form.name = ''
  form.rate_limit_per_min = 60
  form.burst = 10
  form.token_quota = 200000
  form.scopes = ['chat', 'embeddings']
  formVisible.value = true
}

function openEdit(key: ApiKeyInfo): void {
  editing.value = key
  form.name = key.name
  form.rate_limit_per_min = key.rate_limit_per_min
  form.burst = key.burst
  form.token_quota = key.token_quota
  form.scopes = key.scopes || []
  formVisible.value = true
}

async function submitForm(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('请填写 Key 名称')
    return
  }
  submitting.value = true
  try {
    if (editing.value) {
      await keyApi.update(editing.value.id, {
        name: form.name.trim(),
        rate_limit_per_min: form.rate_limit_per_min,
        burst: form.burst,
        token_quota: form.token_quota,
      })
      ElMessage.success('已保存')
      formVisible.value = false
    } else {
      const created = await keyApi.create({
        name: form.name.trim(),
        rate_limit_per_min: form.rate_limit_per_min,
        burst: form.burst,
        token_quota: form.token_quota,
        scopes: form.scopes,
      })
      formVisible.value = false
      plainKey.value = created.plain_key || ''
      plainVisible.value = true
    }
    await loadKeys()
  } finally {
    submitting.value = false
  }
}

async function toggle(key: ApiKeyInfo, active: boolean): Promise<void> {
  await keyApi.update(key.id, { active })
  ElMessage.success(active ? '已启用' : '已禁用')
  await loadKeys()
}

async function remove(key: ApiKeyInfo): Promise<void> {
  await ElMessageBox.confirm(`确认删除 API Key「${key.name}」？历史用量记录会保留。`, '删除确认', { type: 'warning' })
  await keyApi.remove(key.id)
  ElMessage.success('已删除')
  await loadKeys()
}

async function copyPlainKey(): Promise<void> {
  try {
    await navigator.clipboard.writeText(plainKey.value)
    localStorage.setItem('mops_demo_key', plainKey.value)
    ElMessage.success('已复制，并保存到本地供调试台使用')
  } catch {
    ElMessage.warning('复制失败，请手动选中文本复制')
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.stat-row {
  margin-bottom: 4px;
}

.stat-mini {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
}

.stat-mini span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.stat-mini b {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}

.card-title {
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
}

.small {
  font-size: 11px;
}

.quota-text {
  margin-top: 2px;
}

.logs-card {
  margin-top: 14px;
}

.log-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 12px;
  font-size: 12px;
  word-break: break-all;
}

.error-text {
  color: var(--el-color-danger);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.plain-key {
  display: block;
  margin: 14px 0 4px;
  padding: 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 13px;
  word-break: break-all;
}
</style>
