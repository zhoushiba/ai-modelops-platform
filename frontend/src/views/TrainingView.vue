<template>
  <div>
    <div class="page-header">
      <div>
        <h2>训练任务</h2>
        <p>选择数据集版本与训练器提交任务，后台工作者异步执行，可看日志、指标并取消</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">提交训练任务</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-input
        v-model="filters.q"
        placeholder="搜索任务名称"
        clearable
        style="width: 240px"
        :prefix-icon="Search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-select v-model="filters.status" placeholder="状态" clearable style="width: 150px" @change="onSearch">
        <el-option value="queued" label="排队中" />
        <el-option value="running" label="训练中" />
        <el-option value="succeeded" label="已完成" />
        <el-option value="failed" label="失败" />
        <el-option value="canceled" label="已取消" />
      </el-select>
      <el-button @click="onSearch">查询</el-button>
      <span class="muted">共 {{ total }} 个任务</span>
    </div>

    <AsyncState :loading="loading && !items.length" :error="error" :rows="6" @retry="load">
      <div class="card">
        <el-table :data="items" style="width: 100%">
          <el-table-column label="任务" min-width="220">
            <template #default="{ row }">
              <div class="name-cell">
                <b>{{ row.name }}</b>
                <span class="muted mono">job#{{ row.id }} · {{ row.base_model }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="任务类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ taskTypeLabel(row.task_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数据集" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.dataset_name }} <span class="mono muted">v{{ row.dataset_version }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="170">
            <template #default="{ row }">
              <el-tag :type="jobStatus(row.status).type" effect="light" size="small">
                {{ jobStatus(row.status).text }}
              </el-tag>
              <el-progress
                v-if="row.status === 'running' || row.status === 'queued'"
                :percentage="row.progress"
                :stroke-width="6"
                :show-text="false"
                class="row-progress"
              />
              <div v-else-if="row.status === 'running'" class="muted small">{{ row.status_message }}</div>
            </template>
          </el-table-column>
          <el-table-column label="关键指标" width="190">
            <template #default="{ row }">
              <template v-if="row.metrics?.accuracy !== undefined">
                <div class="mono">accuracy {{ formatPercent(row.metrics.accuracy, 2) }}</div>
                <div class="mono muted">F1 {{ formatPercent(row.metrics.f1_macro, 2) }}</div>
              </template>
              <template v-else-if="row.metrics?.chunk_count">
                <div class="mono">{{ row.metrics.doc_count }} docs / {{ row.metrics.chunk_count }} chunks</div>
                <div class="mono muted">self-hit {{ formatPercent(row.metrics.self_hit_rate, 0) }}</div>
              </template>
              <span v-else class="muted">{{ row.error ? row.error : '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column label="提交时间" width="165">
            <template #default="{ row }">{{ formatDateTime(row.queued_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDetail(row)">详情</el-button>
              <el-button
                v-if="['queued', 'running'].includes(row.status)"
                text
                type="danger"
                size="small"
                @click="cancel(row)"
              >
                取消
              </el-button>
              <el-button
                v-else-if="row.status === 'succeeded' && !row.model_version_id"
                text
                type="primary"
                size="small"
                @click="register(row)"
              >
                注册模型
              </el-button>
              <el-tag v-else-if="row.model_version_id" size="small" type="success" effect="plain">
                已注册
              </el-tag>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="70" description="还没有训练任务，点击右上角提交第一个" />
          </template>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            :page-size="size"
            :total="total"
            layout="prev, pager, next, total"
            background
            @current-change="load"
          />
        </div>
      </div>
    </AsyncState>

    <!-- 提交任务 -->
    <el-dialog v-model="createVisible" title="提交训练任务" width="620px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="任务名称" required>
          <el-input v-model="form.name" maxlength="128" placeholder="例如：工单分类 TF-IDF baseline" />
        </el-form-item>
        <el-form-item label="训练器" required>
          <el-select v-model="form.task_type" style="width: 100%" @change="onTaskTypeChange">
            <el-option
              v-for="trainer in trainers"
              :key="trainer.task_type"
              :value="trainer.task_type"
              :label="`${trainer.display_name}（${trainer.task_type}）`"
            />
          </el-select>
          <div v-if="currentTrainer" class="muted hint">{{ currentTrainer.description }}</div>
        </el-form-item>
        <el-form-item label="数据集">
          <div class="dataset-row">
            <el-select v-model="form.dataset_id" placeholder="选择数据集" filterable style="flex: 1" @change="onDatasetChange">
              <el-option
                v-for="dataset in datasets"
                :key="dataset.id"
                :value="dataset.id"
                :label="`${dataset.name}（${taskTypeLabel(dataset.task_type)}）`"
              />
            </el-select>
            <el-select v-model="form.dataset_version_id" placeholder="选择版本" style="width: 160px">
              <el-option
                v-for="version in datasetVersions"
                :key="version.id"
                :value="version.id"
                :label="`v${version.version} · ${version.row_count} 条`"
              />
            </el-select>
          </div>
        </el-form-item>
        <el-form-item label="基础模型">
          <el-input v-model="form.base_model" readonly />
        </el-form-item>

        <el-divider content-position="left">超参数</el-divider>
        <template v-if="form.task_type === 'text_classification'">
          <el-form-item label="epochs">
            <el-input-number v-model="form.hyperparams.epochs" :min="1" :max="50" />
            <span class="muted hint">每个 epoch 重新拟合一次并记录 loss/acc</span>
          </el-form-item>
          <el-form-item label="lr（C）">
            <el-input-number v-model="form.hyperparams.lr" :min="0.01" :max="100" :step="0.1" :precision="2" />
          </el-form-item>
          <el-form-item label="max_len">
            <el-input-number v-model="form.hyperparams.max_len" :min="16" :max="4096" :step="16" />
          </el-form-item>
          <el-form-item label="max_features">
            <el-input-number v-model="form.hyperparams.max_features" :min="100" :max="200000" :step="500" />
          </el-form-item>
          <el-form-item label="char n-gram">
            <el-input-number v-model="form.hyperparams.ngram_max" :min="1" :max="3" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="chunk_size">
            <el-input-number v-model="form.hyperparams.chunk_size" :min="20" :max="2000" :step="20" />
          </el-form-item>
          <el-form-item label="chunk_overlap">
            <el-input-number v-model="form.hyperparams.chunk_overlap" :min="0" :max="1000" :step="10" />
          </el-form-item>
          <el-form-item label="向量维度">
            <el-input-number v-model="form.hyperparams.embedding_dim" :min="64" :max="4096" :step="64" />
            <span class="muted hint">/v1/embeddings 输出的维度</span>
          </el-form-item>
        </template>

        <el-divider content-position="left">交付</el-divider>
        <el-form-item label="自动注册">
          <el-switch v-model="form.auto_register" />
          <span class="muted hint">训练成功后自动写入模型注册表（staging）</span>
        </el-form-item>
        <el-form-item v-if="form.auto_register" label="模型名称">
          <el-input v-model="form.register_as" placeholder="留空则使用任务名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">提交并开始训练</el-button>
      </template>
    </el-dialog>

    <!-- 任务详情 -->
    <el-drawer v-model="drawerVisible" :title="current ? `任务详情 · ${current.name}` : '任务详情'" size="72%">
      <template v-if="current">
        <div class="detail-head">
          <div>
            <el-tag :type="jobStatus(current.status).type" effect="light">{{ jobStatus(current.status).text }}</el-tag>
            <span class="muted mono head-id">job#{{ current.id }} · {{ current.base_model }}</span>
          </div>
          <div class="actions">
            <el-button v-if="['queued', 'running'].includes(current.status)" size="small" type="danger" plain @click="cancel(current)">
              取消任务
            </el-button>
            <el-button size="small" :icon="Refresh" :loading="detailLoading" @click="refreshDetail">刷新</el-button>
          </div>
        </div>

        <el-progress
          v-if="['queued', 'running'].includes(current.status)"
          :percentage="current.progress"
          :stroke-width="10"
          striped
          striped-flow
          class="progress"
        />

        <div class="grid-cards metrics">
          <div class="stat-card">
            <span class="label">数据集</span>
            <span class="value small-value">{{ current.dataset_name || '—' }}</span>
            <span class="sub">v{{ current.dataset_version }} · {{ taskTypeLabel(current.task_type) }}</span>
          </div>
          <div class="stat-card">
            <span class="label">耗时</span>
            <span class="value">{{ formatDuration(current.duration_ms) }}</span>
            <span class="sub">{{ formatDateTime(current.started_at) }} → {{ formatDateTime(current.finished_at) }}</span>
          </div>
          <template v-if="current.metrics?.accuracy !== undefined">
            <div class="stat-card">
              <span class="label">验证集准确率</span>
              <span class="value">{{ formatPercent(current.metrics.accuracy, 2) }}</span>
              <span class="sub">train {{ current.metrics.train_size }} / val {{ current.metrics.val_size }}</span>
            </div>
            <div class="stat-card">
              <span class="label">Macro F1</span>
              <span class="value">{{ formatPercent(current.metrics.f1_macro, 2) }}</span>
              <span class="sub">
                P {{ formatPercent(current.metrics.precision_macro, 2) }} · R
                {{ formatPercent(current.metrics.recall_macro, 2) }}
              </span>
            </div>
          </template>
          <template v-else-if="current.metrics?.chunk_count">
            <div class="stat-card">
              <span class="label">文档 / 切片</span>
              <span class="value">{{ current.metrics.doc_count }} / {{ current.metrics.chunk_count }}</span>
              <span class="sub">平均 {{ current.metrics.avg_chunk_chars }} 字符</span>
            </div>
            <div class="stat-card">
              <span class="label">向量维度 / 自检命中</span>
              <span class="value">{{ current.metrics.embedding_dim }}</span>
              <span class="sub">self-hit {{ formatPercent(current.metrics.self_hit_rate, 1) }}</span>
            </div>
          </template>
        </div>

        <el-alert
          v-if="current.error"
          :title="`任务失败：${current.error}`"
          type="error"
          :closable="false"
          show-icon
          class="issue"
        />

        <el-tabs v-model="detailTab">
          <el-tab-pane label="训练日志" name="logs">
            <div class="log-view">
              <div v-for="log in logs" :key="log.id" class="log-line">
                <span class="log-time">{{ formatDateTime(log.ts).slice(11) }}</span>
                <span :class="`log-level-${(log.level || 'info').toLowerCase()}`">{{ log.level }}</span>
                <span>{{ log.message }}</span>
              </div>
              <div v-if="!logs.length" class="muted">暂无日志</div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="逐轮指标" name="metrics">
            <el-table :data="metricPoints" size="small" max-height="320">
              <el-table-column prop="epoch" label="epoch" width="90" />
              <el-table-column prop="name" label="指标" width="150" />
              <el-table-column label="值" width="160">
                <template #default="{ row }"><span class="mono">{{ row.value }}</span></template>
              </el-table-column>
              <template #empty>
                <el-empty :image-size="60" description="任务完成后展示逐 epoch 指标" />
              </template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="产物与配置" name="artifact">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="超参数">
                <span class="mono">{{ JSON.stringify(current.hyperparams) }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="产物路径">
                <span class="mono">{{ current.artifact_path || '—' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="产物大小">{{ formatBytes(current.artifact_size) }}</el-descriptions-item>
              <el-descriptions-item label="SHA-256">
                <span class="mono">{{ truncate(current.artifact_sha256, 32) }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="提交人">{{ current.created_by }}</el-descriptions-item>
              <el-descriptions-item label="模型版本">
                {{ current.model_version_id ? `#${current.model_version_id}` : '未注册' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { datasetApi, trainingApi } from '@/api'
import type { Dataset, DatasetVersion, MetricPoint, TrainerInfo, TrainingJob, TrainingLog } from '@/types'
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  formatPercent,
  jobStatus,
  taskTypeLabel,
  truncate,
} from '@/utils/format'

const loading = ref(false)
const error = ref('')
const items = ref<TrainingJob[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const filters = reactive({ q: '', status: '' })

const trainers = ref<TrainerInfo[]>([])
const datasets = ref<Dataset[]>([])
const datasetVersions = ref<DatasetVersion[]>([])
const createVisible = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  task_type: 'text_classification',
  dataset_id: undefined as number | undefined,
  dataset_version_id: undefined as number | undefined,
  base_model: 'tfidf-logreg',
  auto_register: true,
  register_as: '',
  hyperparams: {
    epochs: 6,
    lr: 1.0,
    max_len: 256,
    max_features: 8000,
    ngram_max: 2,
    batch_size: 32,
    embedding_dim: 384,
    chunk_size: 220,
    chunk_overlap: 40,
  },
})

const drawerVisible = ref(false)
const current = ref<TrainingJob | null>(null)
const logs = ref<TrainingLog[]>([])
const metricPoints = ref<MetricPoint[]>([])
const detailTab = ref('logs')
const detailLoading = ref(false)
let poller: number | undefined

const currentTrainer = computed(() => trainers.value.find((trainer) => trainer.task_type === form.task_type))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await trainingApi.list({
      q: filters.q || undefined,
      status: filters.status || undefined,
      page: page.value,
      size: size.value,
    })
    items.value = result.items
    total.value = result.total
  } catch (err) {
    error.value = (err as Error).message || '加载训练任务失败'
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  page.value = 1
  void load()
}

async function openCreate(): Promise<void> {
  if (!trainers.value.length) trainers.value = await trainingApi.trainers()
  if (!datasets.value.length) datasets.value = (await datasetApi.list({ page: 1, size: 50 })).items
  form.name = ''
  form.dataset_id = undefined
  form.dataset_version_id = undefined
  form.auto_register = true
  form.register_as = ''
  createVisible.value = true
}

function onTaskTypeChange(taskType: string): void {
  const trainer = trainers.value.find((item) => item.task_type === taskType)
  form.base_model = trainer?.base_models?.[0] || ''
}

async function onDatasetChange(datasetId: number): Promise<void> {
  form.dataset_version_id = undefined
  const result = await datasetApi.versions(datasetId)
  datasetVersions.value = result.items
  if (result.items.length) form.dataset_version_id = result.items[0].id
}

async function submit(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!form.dataset_version_id) {
    ElMessage.warning('请选择数据集版本')
    return
  }
  submitting.value = true
  try {
    const job = await trainingApi.create({
      name: form.name,
      dataset_version_id: form.dataset_version_id,
      task_type: form.task_type,
      base_model: form.base_model,
      hyperparams: { ...form.hyperparams },
      auto_register: form.auto_register,
      register_as: form.register_as,
    })
    ElMessage.success(`任务 job#${job.id} 已入队`)
    createVisible.value = false
    await load()
    openDetail(job)
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: TrainingJob): Promise<void> {
  drawerVisible.value = true
  current.value = row
  logs.value = []
  metricPoints.value = []
  detailTab.value = 'logs'
  await refreshDetail()
  startPolling()
}

async function refreshDetail(): Promise<void> {
  if (!current.value) return
  detailLoading.value = true
  try {
    const [detail, logResult, metricResult] = await Promise.all([
      trainingApi.detail(current.value.id),
      trainingApi.logs(current.value.id),
      trainingApi.metrics(current.value.id),
    ])
    current.value = detail
    logs.value = logResult.items
    metricPoints.value = metricResult.items
    const index = items.value.findIndex((item) => item.id === detail.id)
    if (index >= 0) items.value[index] = detail
  } catch {
    // 轮询失败不打断页面，保留已有数据
  } finally {
    detailLoading.value = false
  }
}

function startPolling(): void {
  stopPolling()
  poller = window.setInterval(() => {
    if (!drawerVisible.value || !current.value) return
    if (!['queued', 'running'].includes(current.value.status)) {
      stopPolling()
      return
    }
    void refreshDetail()
  }, 2500)
}

function stopPolling(): void {
  if (poller) {
    window.clearInterval(poller)
    poller = undefined
  }
}

async function cancel(row: TrainingJob): Promise<void> {
  await trainingApi.cancel(row.id)
  ElMessage.success('已请求取消任务')
  await load()
  if (current.value?.id === row.id) await refreshDetail()
}

async function register(row: TrainingJob): Promise<void> {
  await trainingApi.register(row.id, { model_name: row.name, description: '' })
  ElMessage.success('模型已注册到注册表')
  await load()
}

onMounted(async () => {
  await load()
  trainers.value = await trainingApi.trainers().catch(() => [])
  if (trainers.value.length) onTaskTypeChange(form.task_type)
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.row-progress {
  margin-top: 6px;
  width: 120px;
}

.small {
  font-size: 11px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.dataset-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.hint {
  margin-left: 10px;
  font-size: 12px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.head-id {
  margin-left: 10px;
}

.progress {
  margin-bottom: 16px;
}

.metrics {
  margin-bottom: 16px;
}

.small-value {
  font-size: 16px !important;
}

.issue {
  margin-bottom: 14px;
}
</style>
