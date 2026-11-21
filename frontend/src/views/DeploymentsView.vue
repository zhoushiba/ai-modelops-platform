<template>
  <div>
    <div class="page-header">
      <div>
        <h2>推理部署</h2>
        <p>把模型版本一键加载到进程内运行时，对外提供 OpenAI 兼容接口（/v1/chat/completions、/v1/embeddings）</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">一键部署</el-button>
      </div>
    </div>

    <AsyncState :loading="loading && !items.length" :error="error" :rows="5" @retry="load">
      <div class="card">
        <el-table :data="items" style="width: 100%">
          <el-table-column label="服务" min-width="200">
            <template #default="{ row }">
              <div class="name-cell">
                <b>{{ row.name }}</b>
                <span class="muted desc">
                  alias: <code class="mono">{{ row.alias }}</code>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="模型版本" min-width="170">
            <template #default="{ row }">
              <div>{{ row.model_name }}</div>
              <div class="muted mono small">v{{ row.model_version }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="deployStatus(row.status).type" effect="light" size="small">
                {{ deployStatus(row.status).text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="调用量" width="100">
            <template #default="{ row }"><span class="mono">{{ row.request_count }}</span></template>
          </el-table-column>
          <el-table-column label="平均延迟" width="110">
            <template #default="{ row }"><span class="mono">{{ row.avg_latency_ms }} ms</span></template>
          </el-table-column>
          <el-table-column label="QPS 上限" width="100">
            <template #default="{ row }"><span class="mono">{{ row.qps_limit }}</span></template>
          </el-table-column>
          <el-table-column label="最近调用" width="165">
            <template #default="{ row }">
              {{ row.last_request_at ? formatDateTime(row.last_request_at) : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openStats(row)">统计</el-button>
              <el-button
                v-if="row.status !== 'running'"
                text
                type="success"
                size="small"
                @click="start(row)"
              >
                启动
              </el-button>
              <el-button v-else text type="warning" size="small" @click="stop(row)">停止</el-button>
              <el-button text type="primary" size="small" @click="useInPlayground(row)">去调试</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有部署，先在模型注册表里把某个版本设为 production 再部署" />
          </template>
        </el-table>
      </div>
    </AsyncState>

    <!-- 在线推理调试台 -->
    <div class="card playground">
      <div class="playground-head">
        <div>
          <h3>在线推理调试台</h3>
          <p class="muted">直接请求后端 OpenAI 兼容接口 <code>/v1/chat/completions</code>，请求头带 <code>Authorization: Bearer &lt;API Key&gt;</code>。</p>
        </div>
        <el-tag v-if="lastMeta" type="success" effect="plain">
          {{ lastMeta.status }} · {{ lastMeta.latency }} ms · trace {{ lastMeta.trace_id || '—' }}
        </el-tag>
      </div>

      <el-row :gutter="16">
        <el-col :span="10">
          <el-form label-position="top">
            <el-form-item label="目标服务（model 字段）">
              <el-select v-model="playground.model" placeholder="选择运行中的服务" style="width: 100%">
                <el-option
                  v-for="dep in runningDeployments"
                  :key="dep.id"
                  :value="dep.alias || dep.name"
                  :label="`${dep.name}（v${dep.model_version}）`"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="API Key（明文，仅本地使用）">
              <el-input v-model="playground.apiKey" placeholder="mops_xxxxxxxx" show-password>
                <template #append>
                  <el-button @click="createDemoKey" :loading="keyBusy">新建 Key</el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="用户消息 content">
              <el-input
                v-model="playground.prompt"
                type="textarea"
                :rows="5"
                placeholder="例如：我的订单一直显示待发货，能帮我查一下吗？"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="calling" :icon="Promotion" @click="callChat">
                发送推理请求
              </el-button>
              <el-button @click="playground.response = ''">清空结果</el-button>
            </el-form-item>
          </el-form>
        </el-col>
        <el-col :span="14">
          <div class="panel-label">响应</div>
          <pre class="code-block response">{{ playground.response || '响应会显示在这里：包含 OpenAI 官方结构 + 平台追加的 modelops 元信息（trace_id、deployment_id）。' }}</pre>
          <div class="panel-label">等价 curl</div>
          <pre class="code-block">{{ curlSnippet }}</pre>
        </el-col>
      </el-row>
    </div>

    <!-- 统计 -->
    <el-drawer v-model="statsVisible" :title="statsTitle" size="60%">
      <template v-if="stats">
        <el-row :gutter="12" class="stat-row">
          <el-col :span="6"><div class="mini-stat"><span>总调用</span><b>{{ stats.request_count }}</b></div></el-col>
          <el-col :span="6"><div class="mini-stat"><span>24h 调用</span><b>{{ stats.requests_24h }}</b></div></el-col>
          <el-col :span="6">
            <div class="mini-stat"><span>24h 错误率</span><b>{{ formatPercent(stats.error_rate_24h, 2) }}</b></div>
          </el-col>
          <el-col :span="6">
            <div class="mini-stat"><span>平均延迟</span><b>{{ stats.avg_latency_ms }} ms</b></div>
          </el-col>
        </el-row>
        <div class="muted runtime-hint">
          运行时已加载：{{ stats.runtime_loaded ? '是' : '否' }} · 近 1 分钟请求 {{ stats.requests_last_minute }} 次
          <span v-if="stats.last_error"> · 最近错误：{{ stats.last_error }}</span>
        </div>

        <div class="panel-label">近 24 小时调用量（按小时）</div>
        <div class="bars">
          <div v-for="(bar, index) in seriesBars" :key="index" class="bar-item" :title="`${bar.label} · ${bar.value} 次`">
            <div class="bar" :style="{ height: `${bar.height}%` }" />
            <span class="bar-label">{{ bar.label }}</span>
          </div>
          <div v-if="!seriesBars.length" class="muted empty-inline">近 24 小时还没有调用记录</div>
        </div>

        <div class="panel-label">明细</div>
        <el-table :data="stats.series" size="small" max-height="320">
          <el-table-column prop="hour" label="小时" min-width="150" />
          <el-table-column prop="requests" label="调用次数" width="100" />
          <el-table-column prop="avg_latency_ms" label="平均延迟(ms)" width="130" />
          <el-table-column prop="errors" label="错误数" width="100" />
          <template #empty><el-empty :image-size="50" description="暂无数据" /></template>
        </el-table>
      </template>
    </el-drawer>

    <!-- 新建部署 -->
    <el-dialog v-model="createVisible" title="一键部署模型版本" width="560px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="110px">
        <el-form-item label="服务名称" prop="name">
          <el-input v-model="createForm.name" placeholder="如：ticket-classifier-online" />
        </el-form-item>
        <el-form-item label="模型" prop="registryId">
          <el-select v-model="createForm.registryId" placeholder="选择模型" style="width: 100%" @change="onRegistryChange">
            <el-option v-for="model in registries" :key="model.id" :value="model.id" :label="model.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本" prop="modelVersionId">
          <el-select v-model="createForm.modelVersionId" placeholder="选择版本" style="width: 100%">
            <el-option
              v-for="version in createVersions"
              :key="version.id"
              :value="version.id"
              :label="`v${version.version} · ${modelStatus(version.status).text}`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调用别名">
          <el-input v-model="createForm.alias" placeholder="可选，调用时 model 字段可填别名" />
        </el-form-item>
        <el-form-item label="QPS 上限">
          <el-input-number v-model="createForm.qpsLimit" :min="1" :max="1000" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">部署</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Promotion, Refresh } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { deploymentApi, keyApi, modelApi } from '@/api'
import type { Deployment, DeploymentStats, ModelRegistry, ModelVersion } from '@/types'
import { deployStatus, formatDateTime, formatPercent, modelStatus, toLabeledBars } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const items = ref<Deployment[]>([])

const statsVisible = ref(false)
const statsTitle = ref('')
const stats = ref<DeploymentStats | null>(null)

const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
const registries = ref<ModelRegistry[]>([])
const createVersions = ref<ModelVersion[]>([])
const createForm = reactive({
  name: '',
  registryId: null as number | null,
  modelVersionId: null as number | null,
  alias: '',
  qpsLimit: 60,
  description: '',
})
const createRules: FormRules = {
  name: [{ required: true, message: '请输入服务名称', trigger: 'blur' }],
  registryId: [{ required: true, message: '请选择模型', trigger: 'change' }],
  modelVersionId: [{ required: true, message: '请选择版本', trigger: 'change' }],
}

const playground = reactive({
  model: '',
  apiKey: localStorage.getItem('mops_demo_key') || '',
  prompt: '我的订单一直显示待发货，能帮我查一下物流吗？',
  response: '',
})
const calling = ref(false)
const keyBusy = ref(false)
const lastMeta = ref<{ status: number; latency: number; trace_id: string } | null>(null)

const runningDeployments = computed(() => items.value.filter((item) => item.status === 'running'))
const seriesBars = computed(() =>
  toLabeledBars(
    (stats.value?.series || []).map((point) => ({ label: point.hour.slice(11, 16), value: point.requests })),
  ),
)
const curlSnippet = computed(() => {
  const model = playground.model || '<deployment-name-or-alias>'
  return `curl -X POST http://127.0.0.1:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer \${MOPS_API_KEY}" \\
  -d '{"model": "${model}", "messages": [{"role": "user", "content": "你好"}]}'`
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await deploymentApi.list()
    items.value = result.items
    if (!playground.model && runningDeployments.value.length) {
      playground.model = runningDeployments.value[0].alias || runningDeployments.value[0].name
    }
  } catch (err) {
    error.value = (err as Error).message || '加载部署列表失败'
  } finally {
    loading.value = false
  }
}

async function start(row: Deployment): Promise<void> {
  await deploymentApi.start(row.id)
  ElMessage.success(`${row.name} 已启动`)
  await load()
}

async function stop(row: Deployment): Promise<void> {
  await deploymentApi.stop(row.id)
  ElMessage.success(`${row.name} 已停止`)
  await load()
}

async function remove(row: Deployment): Promise<void> {
  await ElMessageBox.confirm(`确认删除部署「${row.name}」？`, '删除确认', { type: 'warning' })
  await deploymentApi.remove(row.id)
  ElMessage.success('已删除')
  await load()
}

async function openStats(row: Deployment): Promise<void> {
  statsTitle.value = `调用统计 · ${row.name}`
  stats.value = await deploymentApi.stats(row.id)
  statsVisible.value = true
}

function useInPlayground(row: Deployment): void {
  playground.model = row.alias || row.name
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  ElMessage.success(`调试台已切换到 ${row.name}`)
}

async function openCreate(): Promise<void> {
  createVisible.value = true
  createForm.name = ''
  createForm.registryId = null
  createForm.modelVersionId = null
  createForm.alias = ''
  createForm.qpsLimit = 60
  createForm.description = ''
  const result = await modelApi.list({ size: 50 })
  registries.value = result.items
}

async function onRegistryChange(registryId: number): Promise<void> {
  createForm.modelVersionId = null
  const detail = await modelApi.detail(registryId)
  createVersions.value = (detail.versions || []).slice().sort((a, b) => b.version - a.version)
  const production = createVersions.value.find((version) => version.status === 'production')
  if (production) createForm.modelVersionId = production.id
}

async function doCreate(): Promise<void> {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid || !createForm.modelVersionId) return
  creating.value = true
  try {
    const deployment = await deploymentApi.create({
      name: createForm.name.trim(),
      model_version_id: createForm.modelVersionId,
      qps_limit: createForm.qpsLimit,
      alias: createForm.alias.trim(),
      description: createForm.description.trim(),
    })
    ElMessage.success(`部署成功：${deployment.name}（${deployment.status}）`)
    createVisible.value = false
    await load()
    playground.model = deployment.alias || deployment.name
  } finally {
    creating.value = false
  }
}

async function createDemoKey(): Promise<void> {
  keyBusy.value = true
  try {
    const key = await keyApi.create({ name: `调试台 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}` })
    if (key.plain_key) {
      playground.apiKey = key.plain_key
      localStorage.setItem('mops_demo_key', key.plain_key)
    }
    ElMessage.success('已新建 API Key（明文只显示这一次）')
  } finally {
    keyBusy.value = false
  }
}

async function callChat(): Promise<void> {
  if (!playground.model) {
    ElMessage.warning('请先选择运行中的服务')
    return
  }
  if (!playground.apiKey.trim()) {
    ElMessage.warning('请填写 API Key（可点「新建 Key」生成一个）')
    return
  }
  calling.value = true
  const startedAt = performance.now()
  try {
    const result = await axios.post(
      '/v1/chat/completions',
      {
        model: playground.model,
        messages: [{ role: 'user', content: playground.prompt }],
        temperature: 0.2,
        max_tokens: 256,
      },
      {
        headers: { Authorization: `Bearer ${playground.apiKey.trim()}` },
        transformResponse: [(data) => data],
      },
    )
    const latency = Math.round(performance.now() - startedAt)
    const data = JSON.parse(String(result.data))
    playground.response = JSON.stringify(data, null, 2)
    lastMeta.value = { status: result.status, latency, trace_id: data?.modelops?.trace_id || '' }
  } catch (err) {
    const axiosErr = err as { response?: { status: number; data: unknown }; message: string }
    playground.response = JSON.stringify(axiosErr.response?.data ?? { message: axiosErr.message }, null, 2)
    lastMeta.value = {
      status: axiosErr.response?.status ?? 0,
      latency: Math.round(performance.now() - startedAt),
      trace_id: '',
    }
  } finally {
    calling.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.desc {
  font-size: 12px;
}

.small {
  font-size: 11px;
}

.playground {
  margin-top: 16px;
}

.playground-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.playground-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
}

.panel-label {
  margin: 8px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.response {
  max-height: 320px;
  margin: 0 0 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

.stat-row {
  margin-bottom: 8px;
}

.runtime-hint {
  margin-bottom: 6px;
  font-size: 12px;
}

.empty-inline {
  padding: 18px 0;
}
</style>
