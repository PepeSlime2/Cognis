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
