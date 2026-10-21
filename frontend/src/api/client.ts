const API_BASE_URL = '/api'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...init.headers,
    },
  })

  const responseText = await response.text()
  let payload: unknown = null
  if (responseText) {
    try {
      payload = JSON.parse(responseText)
    } catch {
      if (response.ok) {
        throw new ApiError('O servidor retornou uma resposta inválida.', response.status)
      }
    }
  }
  if (!response.ok) {
    const message =
      typeof payload === 'object' &&
      payload !== null &&
      'detail' in payload &&
      typeof payload.detail === 'string'
        ? payload.detail
        : 'Não foi possível concluir a solicitação.'
    throw new ApiError(message, response.status)
  }

  return payload as T
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      ...(body === undefined
        ? {}
        : {
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }),
    })
  },

  put<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },

  patch<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },

  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' })
  },
}

export type ProviderConnection = {
  username: string
  connected_at?: string
  status?: string
}

export type ProjectSummary = {
  id: string
  name: string
  timezone: string
  history_days: number
  auto_sync: boolean
  sync_interval_min: number
  next_sync_at?: string | null
  created_at: string
}

export type GraphLayer = 'all' | 'people' | 'tasks' | 'artifacts'

export type GraphNodeData = {
  id: string
  label: string
  type: string
  size_metric: number
  community: string | null
  flags: string[]
  metrics: Record<string, number>
  status_category: string | null
  url: string | null
}

export type GraphEdgeData = {
  id: string
  source: string
  target: string
  type: string
  weight: number
  breakdown: Record<string, unknown>
}

export type ProjectGraph = {
  elements: {
    nodes: Array<{ data: GraphNodeData }>
    edges: Array<{ data: GraphEdgeData }>
  }
  truncated: boolean
  stats: {
    nodes: number
    edges: number
  }
}

export type SyncRun = {
  run_id: string
  project_id: string
  status: 'queued' | 'running' | 'success' | 'partial' | 'failed'
  started_at: string
  finished_at: string | null
  progress: {
    stage?: string
    done?: number
    total?: number
    message?: string
  }
  stats: Record<string, unknown>
  errors: Array<{
    code?: string
    message?: string
    source_id?: string
  }>
}

export type SyncStartResponse = {
  run_id: string
  status: 'queued' | 'running'
  progress: SyncRun['progress']
}

export type SessionResponse = {
  user_id: string
  email?: string | null
  name?: string | null
  connections: Record<string, ProviderConnection>
}

export const sessionQueryKey = ['auth', 'me'] as const
export const projectsQueryKey = ['projects'] as const

export type ColumnCategory = 'todo' | 'doing' | 'review' | 'done' | 'backlog'

export type ColumnMappingItem = {
  column_uid: string
  name: string
  category: ColumnCategory
  source: 'auto' | 'user'
}

export type ColumnMappingsResponse = {
  columns: ColumnMappingItem[]
  warnings: string[]
}

export type ProjectSettings = {
  auto_sync: boolean
  sync_interval_min: number
  next_sync_at?: string | null
  timezone: string
  history_days: number
  settings_json: Record<string, unknown>
}

export type PersonAccount = {
  uid: string
  provider: string | null
  login: string | null
  display_name: string | null
  avatar_url: string | null
  is_bot: boolean
  linked: boolean
}

export type Person = {
  person_uid: string
  display_name: string | null
  excluded: boolean
  is_me: boolean
  accounts: PersonAccount[]
}

export type MergeSuggestion = {
  person_a_uid: string
  person_b_uid: string
  account_a: PersonAccount | null
  account_b: PersonAccount
  reason: string
  confidence: number
}

export type PeopleResponse = {
  project_id: string
  people: Person[]
  suggestions: MergeSuggestion[]
}

export type ProjectLink = {
  source_uid: string
  source_title: string
  source_provider: string
  source_url: string | null
  target_uid: string
  target_title: string
  target_provider: string
  target_kind: 'pull_request' | 'issue'
  target_url: string | null
  via: string
  confidence: number
}

export type LinksResponse = {
  project_id: string
  links: ProjectLink[]
  unlinked_tasks: Array<{
    uid: string
    title: string
    provider: string
    url: string | null
    short_link: string | null
  }>
  candidates: Array<{
    uid: string
    title: string
    kind: 'pull_request' | 'issue'
    provider: string
    url: string | null
  }>
}

export type MetricCatalogEntry = {
  id: string
  name: string
  category: string
  scope: string
  unit: string
  description: string
  formula: string
  min_sample: string
}

export type MetricResult = {
  id: string
  scope: string
  status: 'ok' | 'insufficient_data' | 'not_applicable'
  unit: string
  values: Record<string, unknown> | number | string | boolean | null
  reason: string | null
  inputs: Record<string, unknown>
  formula_version?: number
}

export type MetricsBundle = {
  project_id: string
  window: {
    from: string
    to: string
    timezone: string
    start_utc: string
    end_utc: string
    duration_days: number
  }
  data_version: string
  config_hash: string
  generated_at: string
  warnings: string[]
  metrics: Record<string, MetricResult>
  signals: Signal[]
  cached: boolean
}

export type SignalSeverity = 'info' | 'medium' | 'high'

export type SignalSubject = {
  type: 'person' | 'module' | 'team'
  id: string
  label: string
}

export type SignalEvidence = {
  metric_id: string
  value: unknown
  unit: string
}

export type Signal = {
  id: string
  code: string
  severity: SignalSeverity
  title: string
  message: string
  subject: SignalSubject
  evidence: SignalEvidence[]
  window: {
    from: string
    to: string
    [key: string]: unknown
  }
}

export type Sprint = {
  id: string
  project_id: string
  name: string
  start_date: string | null
  end_date: string | null
  start_civil: string | null
  end_civil: string | null
}

export type AnalysisScope = 'team' | 'collaboration' | 'risks' | 'sprint' | 'person'

export type AnalysisEvidence = {
  ref: string
}

export type AnalysisFinding = {
  titulo: string
  descricao: string
  severidade: 'baixa' | 'media' | 'alta'
  evidencias: AnalysisEvidence[]
}

export type AnalysisRecommendation = {
  acao: string
  justificativa: string
  evidencias: AnalysisEvidence[]
}

export type AnalysisSection = {
  resumo: string
  achados: AnalysisFinding[]
  recomendacoes: AnalysisRecommendation[]
  limitacoes: string[]
}

export type AnalysisValidation = {
  passed: boolean
  retries?: number
  violations?: string[]
  source?: string
  error?: string
  [key: string]: unknown
}

export type Analysis = {
  id: string
  analysis_id: string
  project_id: string
  scope: AnalysisScope | string
  status: 'pending' | 'running' | 'completed' | 'failed'
  model: string | null
  source: 'ollama' | 'template' | 'mixed'
  window: {
    from: string | null
    to: string | null
  }
  person_uid: string | null
  facts: Record<string, unknown>
  result: AnalysisSection | null
  validation: AnalysisValidation | null
  created_at: string | null
}

export type AnalysisCreateRequest = {
  scope?: AnalysisScope | string
  window?: string
  from?: string
  to?: string
  sprint_id?: string
  person_uid?: string
  anonymize?: boolean
  force_template?: boolean
  wait?: boolean
}

export type ReportType = 'sprint' | 'gerencial' | 'individual' | 'gargalos' | 'colaboracao'
export type ReportFormat = 'html' | 'docx' | 'pdf'

export type ReportItem = {
  id: string
  report_id: string
  project_id: string
  type: ReportType
  status: 'pending' | 'processing' | 'completed' | 'failed'
  window: {
    from: string | null
    to: string | null
  }
  person_uid: string | null
  formats: ReportFormat[]
  files: Record<string, string>
  created_at: string | null
}

export type ReportCreateRequest = {
  type: ReportType
  window?: string
  from?: string
  to?: string
  sprint_id?: string
  person_uid?: string
  formats?: ReportFormat[]
  include_ai?: boolean
  anonymize?: boolean
  wait?: boolean
}

export const reportsApi = {
  createReport: (projectId: string, payload: ReportCreateRequest): Promise<ReportItem> =>
    api.post<ReportItem>(`/projects/${projectId}/reports`, payload),
  getReport: (id: string): Promise<ReportItem> =>
    api.get<ReportItem>(`/reports/${id}`),
  listReports: (projectId: string): Promise<ReportItem[]> =>
    api.get<ReportItem[]>(`/projects/${projectId}/reports`),
  getDownloadUrl: (id: string, format: ReportFormat): string =>
    `/api/reports/${id}/download?format=${format}`,
}


