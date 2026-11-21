/** 与后端 serializer 对齐的数据契约（只声明前端真正用到的字段）。 */

export interface User {
  id: number
  username: string
  display_name: string
  role: string
  created_at: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface DatasetVersion {
  id: number
  dataset_id: number
  version: number
  row_count: number
  train_count: number
  val_count: number
  label_count: number
  checksum: string
  stats: Record<string, unknown>
  diff: Record<string, unknown>
  file_path: string
  created_by: string
  created_at: string
  dataset_name?: string
  task_type?: string
}

export interface Dataset {
  id: number
  name: string
  description: string
  task_type: string
  owner: string
  version_count: number
  latest_version: DatasetVersion | null
  created_at: string
  updated_at: string
  versions?: DatasetVersion[]
}

export interface DatasetSample {
  id: number
  row_index: number
  text: string
  label: string
  split: string
  meta: Record<string, unknown>
}

export interface QualityReport {
  row_count: number
  label_count: number
  duplicate_count: number
  duplicate_ratio: number
  empty_count: number
  too_long_count: number
  label_distribution: Record<string, number>
  length_stats: Record<string, number>
  split_distribution: Record<string, number>
  issues: string[]
  checksum?: string
}

export interface VersionDiff {
  previous_version_total: number
  current_version_total: number
  added: number
  removed: number
  label_changed: number
  changed_total: number
  added_examples: string[]
  removed_examples: string[]
  base_version: number
  target_version: number
}

export interface JobMetrics {
  accuracy?: number
  f1_macro?: number
  precision_macro?: number
  recall_macro?: number
  train_size?: number
  val_size?: number
  label_count?: number
  labels?: string[]
  confusion_matrix?: number[][]
  doc_count?: number
  chunk_count?: number
  embedding_dim?: number
  self_hit_rate?: number
  [key: string]: unknown
}

export interface TrainingLog {
  id: number
  ts: string
  level: string
  message: string
}

export interface MetricPoint {
  id: number
  epoch: number
  name: string
  value: number
}

export interface TrainingJob {
  id: number
  name: string
  dataset_version_id: number
  dataset_name: string
  dataset_version: number
  task_type: string
  base_model: string
  hyperparams: Record<string, number>
  status: string
  progress: number
  status_message: string
  error: string
  queued_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number
  artifact_path: string
  artifact_size: number
  artifact_sha256: string
  metrics: JobMetrics
  model_version_id: number | null
  created_by: string
  logs?: TrainingLog[]
  metrics_series?: MetricPoint[]
}

export interface TrainerInfo {
  task_type: string
  display_name: string
  description: string
  base_models: string[]
}

export interface ModelVersion {
  id: number
  registry_id: number
  registry_name: string
  task_type: string
  version: number
  status: string
  framework: string
  metrics: JobMetrics
  hyperparams: Record<string, number>
  labels: string[]
  artifact_size: number
  artifact_sha256: string
  training_job_id: number | null
  training_job_name: string
  model_card_md: string
  created_by: string
  created_at: string
  deployment_count: number
  training_job?: TrainingJob | null
}

export interface ModelRegistry {
  id: number
  name: string
  task_type: string
  description: string
  version_count: number
  production_version: number | null
  best_accuracy: number | null
  latest_version: ModelVersion | null
  created_at: string
  versions?: ModelVersion[]
}

export interface Deployment {
  id: number
  name: string
  alias: string
  description: string
  status: string
  model_version_id: number
  model_name: string
  model_version: number
  task_type: string
  qps_limit: number
  request_count: number
  error_count: number
  avg_latency_ms: number
  last_error: string
  last_request_at: string | null
  started_at: string | null
  stopped_at: string | null
  created_at: string
  curl?: string
}

export interface DeploymentPoint {
  hour: string
  requests: number
  avg_latency_ms: number
  errors: number
}

export interface DeploymentStats {
  deployment_id: number
  status: string
  qps_last_minute: number
  requests_last_minute: number
  request_count: number
  error_count: number
  avg_latency_ms: number
  requests_24h: number
  errors_24h: number
  error_rate_24h: number
  runtime_loaded: boolean
  started_at: string | null
  stopped_at: string | null
  last_error: string
  series: DeploymentPoint[]
}

export interface ApiKeyInfo {
  id: number
  name: string
  prefix: string
  scopes: string[]
  rate_limit_per_min: number
  burst: number
  token_quota: number
  tokens_used: number
  requests_used: number
  quota_used_ratio: number
  active: boolean
  expires_at: string | null
  last_used_at: string | null
  created_at: string
  plain_key?: string
}

export interface UsageSummary {
  total_requests: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  error_requests: number
  error_rate: number
  avg_latency_ms: number
  by_day: { date: string; requests: number; tokens: number; errors: number }[]
  by_endpoint: { endpoint: string; requests: number; tokens: number }[]
  by_key: { key_name: string; requests: number; tokens: number }[]
  by_model: { model_name: string; requests: number; tokens: number }[]
}

export interface InferenceLog {
  id: number
  trace_id: string
  endpoint: string
  model_name: string
  status_code: number
  latency_ms: number
  prompt_preview: string
  response_preview: string
  prompt_tokens: number
  completion_tokens: number
  error: string
  key_name: string
  deployment_name: string
  created_at: string
}

export interface EvalDataset {
  id: number
  name: string
  description: string
  task_type: string
  sample_count: number
  created_at: string
}

export interface EvalRun {
  id: number
  name: string
  model_version_id: number
  model_name: string
  model_version_number: number
  eval_dataset_id: number
  eval_dataset_name: string
  status: string
  metrics: JobMetrics
  error: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  results?: EvalResult[]
}

export interface EvalResult {
  id: number
  sample_index: number
  input_text: string
  expected: string
  predicted: string
  correct: boolean
  score: number
  latency_ms: number
}

export interface EvalCompare {
  runs: EvalRun[]
  metric_names: string[]
  rows: { metric: string; values: { run_id: number; value: number | null }[] }[]
}

export interface PromptTemplate {
  id: number
  name: string
  description: string
  content: string
  variables: string[]
  tags: string
  version: number
  created_at: string
  updated_at: string
}

export interface PromptExperiment {
  id: number
  name: string
  template_a_id: number
  template_b_id: number
  template_a_name: string
  template_b_name: string
  input_text: string
  variables: Record<string, string>
  output_a: string
  output_b: string
  latency_a_ms: number
  latency_b_ms: number
  engine: string
  score_a: number | null
  score_b: number | null
  notes: string
  status: string
  created_at: string
}

export interface DashboardSummary {
  dataset_count: number
  training_job_count: number
  running_job_count: number
  job_success_rate: number
  model_count: number
  production_model_count: number
  deployment_count: number
  running_deployment_count: number
  api_key_count: number
  calls_today: number
  tokens_today: number
  error_rate_today: number
  avg_latency_ms_today: number
  recent_jobs: TrainingJob[]
  recent_calls: InferenceLog[]
}

export interface TimeseriesPoint {
  date: string
  requests: number
  tokens: number
  errors: number
}
