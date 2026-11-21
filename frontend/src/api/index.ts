/** 管理面 API（全部走 `/api` + JWT）。函数名即后端的资源/动作名，便于前后端对照阅读。 */
import { del, download, get, patch, post, put } from './http'
import type {
  ApiKeyInfo,
  DashboardSummary,
  Dataset,
  DatasetSample,
  DatasetVersion,
  Deployment,
  DeploymentPoint,
  DeploymentStats,
  EvalCompare,
  EvalDataset,
  EvalRun,
  InferenceLog,
  LoginResult,
  ModelRegistry,
  ModelVersion,
  PageResult,
  PromptExperiment,
  PromptTemplate,
  QualityReport,
  TimeseriesPoint,
  TrainerInfo,
  TrainingJob,
  TrainingLog,
  MetricPoint,
  UsageSummary,
  User,
  VersionDiff,
} from '@/types'

export const authApi = {
  login: (username: string, password: string) =>
    post<LoginResult>('/auth/login', { username, password }),
  me: () => get<User>('/auth/me'),
}

export const dashboardApi = {
  summary: () => get<DashboardSummary>('/dashboard/summary'),
  timeseries: (days = 7) => get<{ items: TimeseriesPoint[] }>('/dashboard/timeseries', { days }),
}

export const datasetApi = {
  list: (params: { q?: string; task_type?: string; page?: number; size?: number }) =>
    get<PageResult<Dataset>>('/datasets', params),
  detail: (id: number) => get<Dataset>(`/datasets/${id}`),
  remove: (id: number) => del<{ deleted: number }>(`/datasets/${id}`),
  create: (form: FormData) => post<{ dataset: Dataset; version: DatasetVersion }>('/datasets', form),
  addVersion: (id: number, form: FormData) =>
    post<{ dataset: Dataset; version: DatasetVersion }>(`/datasets/${id}/versions`, form),
  versions: (id: number) => get<{ items: DatasetVersion[] }>(`/datasets/${id}/versions`),
  version: (versionId: number) => get<DatasetVersion>(`/dataset-versions/${versionId}`),
  samples: (versionId: number, params: { split?: string; page?: number; size?: number }) =>
    get<PageResult<DatasetSample>>(`/dataset-versions/${versionId}/samples`, params),
  quality: (versionId: number) => get<QualityReport>(`/dataset-versions/${versionId}/quality`),
  diff: (versionId: number, against: number) =>
    get<VersionDiff>(`/dataset-versions/${versionId}/diff`, { against }),
  exportCsv: (versionId: number, filename: string) =>
    download(`/dataset-versions/${versionId}/download`, filename),
}

export const trainingApi = {
  trainers: () => get<TrainerInfo[]>('/training/trainers'),
  list: (params: { status?: string; q?: string; page?: number; size?: number }) =>
    get<PageResult<TrainingJob>>('/training/jobs', params),
  detail: (id: number) => get<TrainingJob>(`/training/jobs/${id}`),
  logs: (id: number, afterId = 0) =>
    get<{ items: TrainingLog[]; status: string; progress: number }>(`/training/jobs/${id}/logs`, {
      after_id: afterId,
      limit: 500,
    }),
  metrics: (id: number) => get<{ items: MetricPoint[] }>(`/training/jobs/${id}/metrics`),
  create: (payload: {
    name: string
    dataset_version_id: number
    task_type: string
    base_model: string
    hyperparams: Record<string, number>
    auto_register: boolean
    register_as: string
  }) => post<TrainingJob>('/training/jobs', payload),
  cancel: (id: number) => post<TrainingJob>(`/training/jobs/${id}/cancel`),
  register: (id: number, payload: { model_name?: string; description?: string }) =>
    post<{ model_version: ModelVersion; already: boolean }>(`/training/jobs/${id}/register`, payload),
}

export const modelApi = {
  list: (params: { q?: string; task_type?: string; page?: number; size?: number }) =>
    get<PageResult<ModelRegistry>>('/models', params),
  detail: (id: number) => get<ModelRegistry>(`/models/${id}`),
  version: (versionId: number) => get<ModelVersion>(`/models/versions/${versionId}`),
  status: (versionId: number, status: string, note = '') =>
    patch<ModelVersion>(`/models/versions/${versionId}/status`, { status, note }),
  card: (versionId: number) =>
    get<{ model_version_id: number; model_card: string }>(`/models/versions/${versionId}/card`),
  rollback: (registryId: number, toVersion?: number) =>
    post<{ registry: ModelRegistry; model_version: ModelVersion }>(`/models/${registryId}/rollback`, {
      to_version: toVersion ?? null,
    }),
}

export const deploymentApi = {
  list: (status = '') => get<{ items: Deployment[] }>('/deployments', { status }),
  detail: (id: number) => get<Deployment>(`/deployments/${id}`),
  create: (payload: {
    name: string
    model_version_id: number
    qps_limit: number
    alias: string
    description: string
  }) => post<Deployment>('/deployments', payload),
  start: (id: number) => post<Deployment>(`/deployments/${id}/start`),
  stop: (id: number) => post<Deployment>(`/deployments/${id}/stop`),
  remove: (id: number) => del<{ deleted: number }>(`/deployments/${id}`),
  stats: (id: number) => get<DeploymentStats>(`/deployments/${id}/stats`),
  timeseries: (id: number, hours = 24) =>
    get<{ items: DeploymentPoint[] }>(`/deployments/${id}/timeseries`, { hours }),
}

export const keyApi = {
  list: () => get<{ items: ApiKeyInfo[] }>('/api-keys'),
  create: (payload: Record<string, unknown>) => post<ApiKeyInfo>('/api-keys', payload),
  update: (id: number, payload: Record<string, unknown>) =>
    patch<ApiKeyInfo>(`/api-keys/${id}`, payload),
  remove: (id: number) => del<{ deleted: number }>(`/api-keys/${id}`),
  usageSummary: (days = 7) => get<UsageSummary>('/usage/summary', { days }),
  usageLogs: (params: { page?: number; size?: number; endpoint?: string; status_code?: number; q?: string }) =>
    get<PageResult<InferenceLog>>('/usage/logs', params),
  recent: (limit = 10) => get<{ items: InferenceLog[] }>('/usage/recent', { limit }),
}

export const evalApi = {
  datasets: () => get<{ items: EvalDataset[] }>('/evals/datasets'),
  createDataset: (form: FormData) => post<EvalDataset>('/evals/datasets', form),
  runs: (model_version_id?: number) =>
    get<{ items: EvalRun[] }>('/evals/runs', model_version_id ? { model_version_id } : {}),
  run: (id: number, includeResults = false) =>
    get<EvalRun>(`/evals/runs/${id}`, { include_results: includeResults }),
  createRun: (payload: { model_version_id: number; eval_dataset_id: number; name: string; max_samples: number }) =>
    post<EvalRun>('/evals/runs', payload),
  compare: (runIds: number[]) => post<EvalCompare>('/evals/compare', { run_ids: runIds }),
}

export const promptApi = {
  list: (q = '') => get<{ items: PromptTemplate[] }>('/prompts', { q }),
  create: (payload: Partial<PromptTemplate>) => post<PromptTemplate>('/prompts', payload),
  update: (id: number, payload: Partial<PromptTemplate>) => put<PromptTemplate>(`/prompts/${id}`, payload),
  remove: (id: number) => del<{ deleted: number }>(`/prompts/${id}`),
  render: (id: number, variables: Record<string, string>) =>
    post<{ rendered: string; missing_variables: string[] }>(`/prompts/${id}/render`, { variables }),
  experiments: (templateId?: number) =>
    get<{ items: PromptExperiment[] }>('/prompts/experiments', templateId ? { template_id: templateId } : {}),
  createExperiment: (payload: {
    name: string
    template_a_id: number
    template_b_id: number
    input_text: string
    variables: Record<string, string>
  }) => post<PromptExperiment>('/prompts/experiments', payload),
  scoreExperiment: (id: number, payload: { score_a: number | null; score_b: number | null; notes: string }) =>
    post<PromptExperiment>(`/prompts/experiments/${id}/score`, payload),
}
