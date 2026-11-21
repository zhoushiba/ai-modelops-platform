<template>
  <div>
    <div class="page-header">
      <div>
        <h2>评估对比</h2>
        <p>用标注评测集对线上模型版本跑离线评测，输出 accuracy / macro-F1 / 延迟，并支持多版本横向对比</p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="reloadAll">刷新</el-button>
        <el-button type="primary" :icon="Upload" @click="openDatasetDialog">上传评测集</el-button>
        <el-button type="success" :icon="VideoPlay" :disabled="!evalDatasets.length || !versions.length" @click="openRunDialog">
          发起评测
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="eval-tabs">
      <el-tab-pane label="评测记录" name="runs">
        <AsyncState :loading="loading && !runs.length" :error="error" :rows="5" @retry="reloadAll">
          <div class="card">
            <el-table :data="runs" style="width: 100%">
              <el-table-column label="评测" min-width="180">
                <template #default="{ row }">
                  <b>{{ row.name || `run#${row.id}` }}</b>
                  <div class="muted small mono">{{ row.model_name }} v{{ row.model_version_number }}</div>
                </template>
              </el-table-column>
              <el-table-column label="评测集" min-width="150" prop="eval_dataset_name" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'succeeded' ? 'success' : row.status === 'failed' ? 'danger' : 'info'" size="small" effect="light">
                    {{ row.status === 'succeeded' ? '成功' : row.status === 'failed' ? '失败' : row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Accuracy" width="110">
                <template #default="{ row }">
                  <span class="mono">{{ formatPercent(row.metrics?.accuracy, 2) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="Macro-F1" width="110">
                <template #default="{ row }">
                  <span class="mono">{{ formatPercent(row.metrics?.f1_macro, 2) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="平均延迟" width="110">
                <template #default="{ row }">
                  <span class="mono">{{ row.metrics?.avg_latency_ms ?? '—' }} ms</span>
                </template>
              </el-table-column>
              <el-table-column label="样本数" width="90">
                <template #default="{ row }">{{ row.metrics?.sample_count ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="完成时间" width="165">
                <template #default="{ row }">{{ formatDateTime(row.finished_at || row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="190" fixed="right">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" @click="openRunDetail(row)">样本明细</el-button>
                  <el-button text type="primary" size="small" :disabled="row.status !== 'succeeded'" @click="toggleCompare(row)">
                    {{ selectedRunIds.includes(row.id) ? '移出对比' : '加入对比' }}
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty :image-size="70" description="还没有评测记录：先在模型注册表产出 production 版本，再点右上角「发起评测」" />
              </template>
            </el-table>
          </div>
        </AsyncState>

        <div v-if="selectedRunIds.length" class="compare-bar card">
          <span>已选 {{ selectedRunIds.length }} 个评测（最多 8 个）</span>
          <el-button type="primary" size="small" :loading="comparing" @click="doCompare">生成对比表</el-button>
          <el-button size="small" @click="selectedRunIds = []">清空</el-button>
        </div>

        <div v-if="compare" class="card compare-card">
          <h3>版本对比</h3>
          <el-table :data="compareRows" size="small" border>
            <el-table-column prop="metric" label="指标" width="180" fixed />
            <el-table-column v-for="run in compare.runs" :key="run.id" :label="`${run.model_name} v${run.model_version_number}`" min-width="150">
              <template #default="{ row }">
                <span class="mono">{{ cellText(row.values[run.id]) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="评测集" name="datasets">
        <div class="card">
          <el-table :data="evalDatasets" style="width: 100%">
            <el-table-column prop="name" label="名称" min-width="200" />
            <el-table-column label="任务类型" width="120">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ taskTypeLabel(row.task_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="sample_count" label="样本数" width="100" />
            <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
            <el-table-column label="创建时间" width="165">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <template #empty><el-empty :image-size="60" description="上传一个 CSV 评测集（text,label 两列）" /></template>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 发起评测 -->
    <el-dialog v-model="runVisible" title="发起离线评测" width="520px">
      <el-form label-width="100px">
        <el-form-item label="评测名称">
          <el-input v-model="runForm.name" placeholder="可选，如：v2 上线前回归" />
        </el-form-item>
        <el-form-item label="模型版本">
          <el-select v-model="runForm.modelVersionId" placeholder="选择模型版本" style="width: 100%" filterable>
            <el-option
              v-for="version in versions"
              :key="version.id"
              :value="version.id"
              :label="`${version.registry_name} v${version.version}（${modelStatus(version.status).text}）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="评测集">
          <el-select v-model="runForm.evalDatasetId" placeholder="选择评测集" style="width: 100%">
            <el-option
              v-for="dataset in evalDatasets"
              :key="dataset.id"
              :value="dataset.id"
              :label="`${dataset.name}（${dataset.sample_count} 条）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="最大样本数">
          <el-input-number v-model="runForm.maxSamples" :min="1" :max="20000" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" show-icon title="评测在服务端同步执行，评测集会逐条推理，样本较多时需要几秒" />
      <template #footer>
        <el-button @click="runVisible = false">取消</el-button>
        <el-button type="primary" :loading="running" @click="doRun">开始评测</el-button>
      </template>
    </el-dialog>

    <!-- 上传评测集 -->
    <el-dialog v-model="datasetVisible" title="上传评测集" width="520px">
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="datasetForm.name" placeholder="如：工单意图评测集-新增" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="datasetForm.task_type" style="width: 100%">
            <el-option value="text_classification" label="文本分类" />
          </el-select>
        </el-form-item>
        <el-form-item label="文本列名">
          <el-input v-model="datasetForm.text_field" />
        </el-form-item>
        <el-form-item label="标签列名">
          <el-input v-model="datasetForm.label_field" />
        </el-form-item>
        <el-form-item label="CSV 文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".csv"
            :on-change="onFileChange"
            :on-remove="() => (datasetForm.file = null)"
          >
            <el-button :icon="Upload">选择 CSV</el-button>
            <template #tip><div class="muted small">UTF-8 编码，首行为表头，至少包含 text / label 两列</div></template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="datasetVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="doUploadDataset">上传</el-button>
      </template>
    </el-dialog>

    <!-- 样本明细 -->
    <el-dialog v-model="detailVisible" :title="detailTitle" width="900px">
      <template v-if="detailRun">
        <el-row :gutter="12" class="stat-row">
          <el-col :span="6"><div class="mini-stat"><span>Accuracy</span><b>{{ formatPercent(detailRun.metrics?.accuracy, 2) }}</b></div></el-col>
          <el-col :span="6"><div class="mini-stat"><span>Macro-F1</span><b>{{ formatPercent(detailRun.metrics?.f1_macro, 2) }}</b></div></el-col>
          <el-col :span="6"><div class="mini-stat"><span>平均延迟</span><b>{{ detailRun.metrics?.avg_latency_ms }} ms</b></div></el-col>
          <el-col :span="6"><div class="mini-stat"><span>样本数</span><b>{{ detailRun.metrics?.sample_count }}</b></div></el-col>
        </el-row>
        <el-alert v-if="detailRun.error" type="error" :closable="false" :title="detailRun.error" class="detail-error" />
        <el-table :data="pagedResults" size="small" max-height="420">
          <el-table-column prop="sample_index" label="#" width="60" />
          <el-table-column prop="input_text" label="输入文本" min-width="280" show-overflow-tooltip />
          <el-table-column prop="expected" label="期望" width="110" />
          <el-table-column prop="predicted" label="预测" width="110" />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.correct ? 'success' : 'danger'" size="small" effect="light">
                {{ row.correct ? '正确' : '错误' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="延迟" width="90">
            <template #default="{ row }"><span class="mono">{{ row.latency_ms }} ms</span></template>
          </el-table-column>
          <template #empty><el-empty :image-size="50" description="暂无样本结果" /></template>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="resultPage"
            :page-size="resultSize"
            :total="detailRun.results?.length || 0"
            layout="prev, pager, next, total"
            background
          />
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { Refresh, Upload, VideoPlay } from '@element-plus/icons-vue'
import AsyncState from '@/components/AsyncState.vue'
import { evalApi, modelApi } from '@/api'
import type { EvalDataset, EvalRun, ModelRegistry, ModelVersion } from '@/types'
import { formatDateTime, formatPercent, modelStatus, taskTypeLabel } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const tab = ref<'runs' | 'datasets'>('runs')

const runs = ref<EvalRun[]>([])
const evalDatasets = ref<EvalDataset[]>([])
const versions = ref<ModelVersion[]>([])

const runVisible = ref(false)
const running = ref(false)
const runForm = reactive({
  name: '',
  modelVersionId: null as number | null,
  evalDatasetId: null as number | null,
  maxSamples: 200,
})

const datasetVisible = ref(false)
const uploading = ref(false)
const datasetForm = reactive({
  name: '',
  task_type: 'text_classification',
  text_field: 'text',
  label_field: 'label',
  file: null as File | null,
})

const detailVisible = ref(false)
const detailTitle = ref('')
const detailRun = ref<EvalRun | null>(null)
const resultPage = ref(1)
const resultSize = ref(20)

const selectedRunIds = ref<number[]>([])
const comparing = ref(false)
const compare = ref<{ runs: EvalRun[]; metric_names: string[]; rows: { metric: string; values: { run_id: number; value: number | null }[] }[] } | null>(null)

const pagedResults = computed(() => {
  const results = detailRun.value?.results || []
  const start = (resultPage.value - 1) * resultSize.value
  return results.slice(start, start + resultSize.value)
})

const compareRows = computed(() => {
  if (!compare.value) return []
  return compare.value.rows.map((row) => {
    const cells: Record<number, number | null> = {}
    for (const item of row.values) cells[item.run_id] = item.value
    return { metric: row.metric, values: cells }
  })
})

async function reloadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [runResult, datasetResult, registries] = await Promise.all([
      evalApi.runs(),
      evalApi.datasets(),
      modelApi.list({ size: 100 }),
    ])
    runs.value = runResult.items
    evalDatasets.value = datasetResult.items
    versions.value = await loadAllVersions(registries.items)
  } catch (err) {
    error.value = (err as Error).message || '加载评测数据失败'
  } finally {
    loading.value = false
  }
}

async function loadAllVersions(registries: ModelRegistry[]): Promise<ModelVersion[]> {
  const details = await Promise.all(registries.map((registry) => modelApi.detail(registry.id)))
  return details.flatMap((detail) => detail.versions || []).sort((a, b) => b.id - a.id)
}

function openRunDialog(): void {
  runVisible.value = true
  runForm.name = ''
  runForm.modelVersionId = versions.value[0]?.id ?? null
  runForm.evalDatasetId = evalDatasets.value[0]?.id ?? null
  runForm.maxSamples = Math.min(200, evalDatasets.value[0]?.sample_count || 200)
}

async function doRun(): Promise<void> {
  if (!runForm.modelVersionId || !runForm.evalDatasetId) {
    ElMessage.warning('请选择模型版本与评测集')
    return
  }
  running.value = true
  try {
    const result = await evalApi.createRun({
      model_version_id: runForm.modelVersionId,
      eval_dataset_id: runForm.evalDatasetId,
      name: runForm.name.trim() || `评测 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
      max_samples: runForm.maxSamples,
    })
    ElMessage.success(`评测完成：accuracy ${formatPercent(result.metrics?.accuracy, 2)}`)
    runVisible.value = false
    await reloadAll()
    tab.value = 'runs'
  } finally {
    running.value = false
  }
}

function openDatasetDialog(): void {
  datasetVisible.value = true
  datasetForm.name = ''
  datasetForm.file = null
}

function onFileChange(file: UploadFile): void {
  datasetForm.file = (file.raw as File) || null
}

async function doUploadDataset(): Promise<void> {
  if (!datasetForm.name.trim() || !datasetForm.file) {
    ElMessage.warning('请填写名称并选择 CSV 文件')
    return
  }
  uploading.value = true
  try {
    const form = new FormData()
    form.append('name', datasetForm.name.trim())
    form.append('task_type', datasetForm.task_type)
    form.append('text_field', datasetForm.text_field)
    form.append('label_field', datasetForm.label_field)
    form.append('file', datasetForm.file)
    await evalApi.createDataset(form)
    ElMessage.success('评测集已上传')
    datasetVisible.value = false
    await reloadAll()
    tab.value = 'datasets'
  } finally {
    uploading.value = false
  }
}

async function openRunDetail(run: EvalRun): Promise<void> {
  detailTitle.value = `样本明细 · ${run.name || `run#${run.id}`}`
  detailRun.value = await evalApi.run(run.id, true)
  resultPage.value = 1
  detailVisible.value = true
}

function toggleCompare(run: EvalRun): void {
  const index = selectedRunIds.value.indexOf(run.id)
  if (index >= 0) {
    selectedRunIds.value.splice(index, 1)
  } else {
    if (selectedRunIds.value.length >= 8) {
      ElMessage.warning('最多同时对比 8 个评测')
      return
    }
    selectedRunIds.value.push(run.id)
  }
}

async function doCompare(): Promise<void> {
  if (selectedRunIds.value.length < 2) {
    ElMessage.warning('至少选择 2 个评测才能对比')
    return
  }
  comparing.value = true
  try {
    compare.value = await evalApi.compare(selectedRunIds.value)
  } finally {
    comparing.value = false
  }
}

function cellText(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  if (value <= 1) return formatPercent(value, 2)
  return String(value)
}

onMounted(reloadAll)
</script>

<style scoped>
.eval-tabs {
  margin-top: 4px;
}

.small {
  font-size: 11px;
}

.compare-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  font-size: 13px;
}

.compare-card {
  margin-top: 12px;
}

.compare-card h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.stat-row {
  margin-bottom: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

.detail-error {
  margin-bottom: 10px;
}
</style>
