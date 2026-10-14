import { useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Core } from 'cytoscape'
import { useNavigate } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCompress } from '@fortawesome/free-solid-svg-icons'
import {
  api,
  projectsQueryKey,
  type ProjectGraph,
  type ProjectSummary,
  type ProviderConnection,
  type SyncRun,
  type SyncStartResponse,
  type ColumnMappingsResponse,
} from '../../api/client'
import type { DockState, GraphSelection, GraphViewState } from './types'
import GraphTopBar from './GraphTopBar'
import GraphToolbar from './GraphToolbar'
import LeftDock from './LeftDock'
import RightDock from './RightDock'
import GraphCanvas from './GraphCanvas'
import GraphLegend from './GraphLegend'
import { ColumnsModal } from '../ColumnsModal/ColumnsModal'
import styles from './graphShell.module.css'

type ProjectSource = {
  provider: 'github' | 'trello'
  external_id: string
  display_name: string | null
  enabled: boolean
}

type ProjectDetails = ProjectSummary & {
  sources: ProjectSource[]
}

const STORAGE_KEY = 'cognis.ui.docks'

const getDefaultDockState = (): DockState => {
  const isWide = typeof window !== 'undefined' ? window.innerWidth >= 1280 : true
  return {
    leftOpen: true,
    rightOpen: isWide,
    rightTab: 'details',
    focusMode: false,
    leftSection: 'sources',
  }
}

const loadStoredDockState = (): DockState => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<DockState>
      return {
        ...getDefaultDockState(),
        ...parsed,
        focusMode: false, // Não iniciar em foco ao recarregar
      }
    }
  } catch {
    // fallback
  }
  return getDefaultDockState()
}

const saveStoredDockState = (state: DockState) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // ignore
  }
}

type GraphShellProps = {
  projectId: string
  onLogout: () => void | Promise<void>
  connections?: Record<string, ProviderConnection>
}

const GraphShell = ({ projectId, onLogout, connections = {} }: GraphShellProps) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const shellRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [, startTransition] = useTransition()

  // 1. Estado DockState (persistido em localStorage)
  const [dockState, setDockState] = useState<DockState>(loadStoredDockState)

  const updateDockState = useCallback((patch: Partial<DockState>) => {
    setDockState((prev) => {
      const next = { ...prev, ...patch }
      saveStoredDockState(next)
      return next
    })
  }, [])

  // 2. Estado GraphViewState
  const [viewState, setViewState] = useState<GraphViewState>({
    window: '30d',
    layer: 'all',
    includeBots: false,
    sizeBy: 'degree',
    colorBy: 'tipo',
    layout: 'fcose',
    fxLevel: 'full',
    minWeight: 1,
    showLabels: true,
    query: '',
    pathMode: false,
    selection: null,
    highlightIds: [],
  })

  const [graph, setGraph] = useState<Core | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const autoSyncTriggeredRef = useRef(false)

  // Consultas
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get<ProjectDetails>(`/projects/${projectId}`),
  })

  const projectsListQuery = useQuery({
    queryKey: projectsQueryKey,
    queryFn: () => api.get<ProjectSummary[]>('/projects'),
  })

  const hasActiveSource = Boolean(
    projectQuery.data?.sources.some((source) => source.enabled),
  )

  const graphQuery = useQuery({
    queryKey: ['projectGraph', projectId, viewState.layer, viewState.includeBots],
    queryFn: () => {
      const params = new URLSearchParams({
        layer: viewState.layer,
        max_nodes: '400',
        min_weight: '1',
        include_bots: String(viewState.includeBots),
      })
      return api.get<ProjectGraph>(`/projects/${projectId}/graph?${params}`)
    },
    enabled: hasActiveSource,
  })

  const [columnsModalOpen, setColumnsModalOpen] = useState(false)

  const syncMutation = useMutation({
    mutationFn: () => api.post<SyncStartResponse>(`/projects/${projectId}/sync`),
    onSuccess: async (run) => {
      setRunId(run.run_id)
      await queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['projectLatestRun', projectId] })
    },
  })

  const latestRunQuery = useQuery({
    queryKey: ['projectLatestRun', projectId],
    queryFn: () => api.get<SyncRun[]>(`/projects/${projectId}/sync-runs?limit=1`),
    enabled: Boolean(projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.[0]?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const runQuery = useQuery({
    queryKey: ['projectSyncRun', projectId, runId],
    queryFn: () => api.get<SyncRun>(`/projects/${projectId}/sync-runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })

  const columnsQuery = useQuery({
    queryKey: ['projectColumns', projectId],
    queryFn: () => api.get<ColumnMappingsResponse>(`/projects/${projectId}/columns`),
    enabled: Boolean(
      projectId && projectQuery.data?.sources.some((s) => s.provider === 'trello' && s.enabled),
    ),
  })
  const hasUnconfirmedColumns = Boolean(
    columnsQuery.data?.warnings?.includes('columns_unconfirmed'),
  )

  const updateSettingsMutation = useMutation({
    mutationFn: ({ autoSync, intervalMin }: { autoSync: boolean; intervalMin: number }) =>
      api.put(`/projects/${projectId}/settings`, {
        auto_sync: autoSync,
        sync_interval_min: intervalMin,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  useEffect(() => {
    const status = runQuery.data?.status ?? latestRunQuery.data?.[0]?.status
    if (status && status !== 'queued' && status !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    }
  }, [projectId, queryClient, runQuery.data?.status, latestRunQuery.data])

  // Auto-sync na primeira vez
  useEffect(() => {
    autoSyncTriggeredRef.current = false
  }, [projectId])

  const currentSyncRun = runQuery.data ?? latestRunQuery.data?.[0] ?? null
  const activeRun = currentSyncRun?.status === 'queued' || currentSyncRun?.status === 'running'
  const syncInProgress = syncMutation.isPending || activeRun

  useEffect(() => {
    if (
      !hasActiveSource ||
      autoSyncTriggeredRef.current ||
      syncInProgress ||
      !graphQuery.isSuccess ||
      graphQuery.data.stats.nodes > 0 ||
      graphQuery.isFetching
    ) {
      return
    }

    autoSyncTriggeredRef.current = true
    syncMutation.mutate()
  }, [graphQuery.data?.stats.nodes, graphQuery.isFetching, graphQuery.isSuccess, hasActiveSource, syncInProgress, syncMutation])

  // Atalhos de teclado (ignorar se foco em input, textarea, select)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable) {
        if (e.key === 'Escape') {
          target?.blur()
        }
        return
      }

      if (e.key === '/') {
        e.preventDefault()
        searchInputRef.current?.focus()
      } else if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        graph?.fit()
      } else if (e.key === '[') {
        e.preventDefault()
        updateDockState({ leftOpen: !dockState.leftOpen })
      } else if (e.key === ']') {
        e.preventDefault()
        updateDockState({ rightOpen: !dockState.rightOpen })
      } else if (e.key === 'Escape') {
        e.preventDefault()
        if (dockState.focusMode) {
          if (document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen().catch(() => {})
          }
          updateDockState({ focusMode: false })
        }
        setViewState((prev) => ({
          ...prev,
          selection: null,
          pathMode: false,
        }))
        graph?.elements().unselect()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [dockState.focusMode, dockState.leftOpen, dockState.rightOpen, graph, updateDockState])

  // Sincronizar evento de fullscreen
  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!document.fullscreenElement && dockState.focusMode) {
        updateDockState({ focusMode: false })
      }
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [dockState.focusMode, updateDockState])

  // Handlers
  const handleToggleFocus = () => {
    const next = !dockState.focusMode
    if (next) {
      if (shellRef.current?.requestFullscreen && !document.fullscreenElement) {
        shellRef.current.requestFullscreen().catch(() => {})
      }
    } else {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {})
      }
    }
    updateDockState({ focusMode: next })
  }

  const handleSelectionChange = useCallback((sel: GraphSelection) => {
    startTransition(() => {
      setViewState((prev) => ({ ...prev, selection: sel }))
    })
    if (sel) {
      updateDockState({ rightOpen: true, rightTab: 'details' })
    }
  }, [updateDockState])

  const handleSearchSubmit = () => {
    const term = viewState.query.trim().toLowerCase()
    if (!graph || !term) return
    const match = graph.nodes().filter((node) =>
      String(node.data('label') ?? '').toLowerCase().includes(term),
    ).first()

    if (!match.empty()) {
      graph.animate({ center: { eles: match }, zoom: 1.25, duration: 300 })
      match.select()
      handleSelectionChange({
        kind: 'node',
        id: match.id(),
        data: match.data(),
      })
    }
  }

  const handleExportPng = () => {
    if (!graph) return
    const image = graph.png({
      output: 'base64uri',
      bg: '#02001b',
      full: true,
      scale: 2,
    })
    const anchor = document.createElement('a')
    anchor.href = image
    anchor.download = `cognis-${projectQuery.data?.name ?? 'grafo'}.png`
    anchor.click()
  }

  const handleReset = () => {
    setViewState((prev) => ({
      ...prev,
      sizeBy: 'degree',
      colorBy: 'tipo',
      layout: 'fcose',
      minWeight: 1,
      showLabels: true,
      query: '',
      pathMode: false,
      selection: null,
    }))
    graph?.elements().unselect()
    graph?.fit()
  }

  const connectGithub = async () => {
    try {
      const payload = await api.get<{ authorize_url: string }>('/auth/github/login')
      window.location.href = payload.authorize_url
    } catch {
      // ignore
    }
  }

  const connectTrello = async () => {
    try {
      const payload = await api.get<{ authorize_url: string }>('/auth/trello/authorize-url')
      window.location.href = payload.authorize_url
    } catch {
      // ignore
    }
  }

  const graphNodes = graphQuery.data?.elements.nodes
  const isEmpty = graphQuery.isSuccess && graphNodes?.length === 0

  const syncStatusInfo = runQuery.data
    ? {
        status: runQuery.data.status,
        message: runQuery.data.progress.message || runQuery.data.status,
        running: runQuery.data.status === 'queued' || runQuery.data.status === 'running',
        isError: runQuery.data.status === 'failed',
      }
    : activeRun
    ? { status: 'running', message: 'Sincronizando…', running: true }
    : undefined

  // Definir variáveis CSS no shell
  const shellStyle = {
    '--dock-left-w': dockState.leftOpen ? '280px' : '56px',
    '--dock-right-w': dockState.rightOpen ? '340px' : '0px',
  } as React.CSSProperties

  return (
    <div
      ref={shellRef}
      className={`${styles.graphShell} ${dockState.focusMode ? styles.focusModeActive : ''}`}
      style={shellStyle}
    >
      {/* Botão flutuante para sair do modo foco */}
      {dockState.focusMode && (
        <button
          type="button"
          className={styles.exitFocusBtn}
          onClick={handleToggleFocus}
          aria-label="Sair do modo foco"
        >
          <FontAwesomeIcon icon={faCompress} />
          <span>Sair do modo foco (Esc)</span>
        </button>
      )}

      {/* ZONA A: GraphTopBar (56px) */}
      <div className={styles.zoneTopBar}>
        <GraphTopBar
          projectId={projectId}
          projects={projectsListQuery.data}
          leftOpen={dockState.leftOpen}
          onToggleLeft={() => updateDockState({ leftOpen: !dockState.leftOpen })}
          rightOpen={dockState.rightOpen}
          onToggleRight={() => updateDockState({ rightOpen: !dockState.rightOpen })}
          focusMode={dockState.focusMode}
          onToggleFocus={handleToggleFocus}
          windowVal={viewState.window}
          onWindowChange={(w) => setViewState((prev) => ({ ...prev, window: w }))}
          layer={viewState.layer}
          onLayerChange={(layer) => {
            setViewState((prev) => ({ ...prev, layer, selection: null }))
          }}
          searchQuery={viewState.query}
          onSearchChange={(q) => setViewState((prev) => ({ ...prev, query: q }))}
          onSearchSubmit={handleSearchSubmit}
          syncStatus={syncStatusInfo}
          onLogout={onLogout}
          searchInputRef={searchInputRef}
        />
      </div>

      {/* ZONA B: GraphToolbar (48px) */}
      <div className={styles.zoneToolbar}>
        <GraphToolbar
          sizeBy={viewState.sizeBy}
          onSizeByChange={(sizeBy) => setViewState((prev) => ({ ...prev, sizeBy }))}
          colorBy={viewState.colorBy}
          onColorByChange={(colorBy) => setViewState((prev) => ({ ...prev, colorBy }))}
          layout={viewState.layout}
          onLayoutChange={(layout) => setViewState((prev) => ({ ...prev, layout }))}
          minWeight={viewState.minWeight}
          onMinWeightChange={(minWeight) => setViewState((prev) => ({ ...prev, minWeight }))}
          includeBots={viewState.includeBots}
          onIncludeBotsChange={(includeBots) =>
            setViewState((prev) => ({ ...prev, includeBots, selection: null }))
          }
          showLabels={viewState.showLabels}
          onShowLabelsChange={(showLabels) => setViewState((prev) => ({ ...prev, showLabels }))}
          pathMode={viewState.pathMode}
          onTogglePathMode={() => setViewState((prev) => ({ ...prev, pathMode: !prev.pathMode }))}
          onFit={() => graph?.fit()}
          onExportPng={handleExportPng}
          fxLevel={viewState.fxLevel}
          onFxLevelChange={(fxLevel) => setViewState((prev) => ({ ...prev, fxLevel }))}
          onReset={handleReset}
          disabled={!graph}
        />
      </div>

      {/* ZONA D: LeftDock (280px / 56px rail) */}
      <div className={styles.zoneLeftDock}>
        <LeftDock
          isOpen={dockState.leftOpen}
          onOpenSection={(section) => updateDockState({ leftOpen: true, leftSection: section })}
          connections={connections}
          onConnectGithub={() => void connectGithub()}
          onConnectTrello={() => void connectTrello()}
          onSync={() => syncMutation.mutate()}
          syncInProgress={syncInProgress}
          syncRun={currentSyncRun}
          hasActiveSource={hasActiveSource}
          autoSync={projectQuery.data?.auto_sync}
          syncIntervalMin={projectQuery.data?.sync_interval_min}
          nextSyncAt={projectQuery.data?.next_sync_at}
          onUpdateSyncInterval={(autoSync, intervalMin) => {
            updateSettingsMutation.mutate({ autoSync, intervalMin })
          }}
          hasTrelloSource={Boolean(
            projectQuery.data?.sources.some((s) => s.provider === 'trello' && s.enabled),
          )}
          hasUnconfirmedColumns={hasUnconfirmedColumns}
          onOpenColumnsModal={() => setColumnsModalOpen(true)}
        />
      </div>

      {/* ZONA C: GraphCanvas (célula central 1fr × 1fr) */}
      <main className={styles.zoneCanvas} aria-label="Visualização do grafo">
        {/* Aviso de truncamento */}
        {graphQuery.data?.truncated && (
          <div className={styles.truncatedBanner} role="status">
            <span>Visualização limitada a 400 nós e 1.500 relações</span>
          </div>
        )}

        {/* EmptyState / Loading / Erros */}
        {projectQuery.isPending || graphQuery.isPending ? (
          <div className={styles.centerStateCard}>
            <p>Carregando grafo cósmico do projeto...</p>
          </div>
        ) : !hasActiveSource ? (
          <div className={styles.centerStateCard}>
            <h2>Nenhuma fonte conectada</h2>
            <p>Conecte repositórios GitHub ou boards do Trello para carregar o grafo de colaboração.</p>
            <button
              type="button"
              className={styles.actionBtn}
              onClick={() => navigate('/settings')}
            >
              Configurar Projeto
            </button>
          </div>
        ) : graphQuery.isError ? (
          <div className={styles.centerStateCard} role="alert">
            <h2>Não foi possível carregar o grafo</h2>
            <p>
              {graphQuery.error instanceof Error
                ? graphQuery.error.message
                : 'Erro inesperado na consulta ao grafo.'}
            </p>
            <button
              type="button"
              className={styles.actionBtn}
              onClick={() => void graphQuery.refetch()}
            >
              Tentar novamente
            </button>
          </div>
        ) : isEmpty ? (
          <div className={styles.centerStateCard}>
            <h2>Grafo vazio</h2>
            <p>Sincronize os dados para carregar commits, issues e pull requests.</p>
            <button
              type="button"
              className={styles.actionBtn}
              onClick={() => syncMutation.mutate()}
              disabled={syncInProgress}
            >
              {syncInProgress ? 'Sincronizando…' : 'Sincronizar agora'}
            </button>
          </div>
        ) : graphQuery.data ? (
          <>
            <GraphCanvas
              elements={graphQuery.data.elements}
              labelsVisible={viewState.showLabels}
              minWeight={viewState.minWeight}
              layoutName={viewState.layout}
              pathMode={viewState.pathMode}
              onSelectionChange={handleSelectionChange}
              onGraphReady={setGraph}
            />
            <GraphLegend />
          </>
        ) : null}
      </main>

      {/* ZONA E: RightDock (340px) */}
      <div className={styles.zoneRightDock}>
        <RightDock
          isOpen={dockState.rightOpen}
          onClose={() => updateDockState({ rightOpen: false })}
          activeTab={dockState.rightTab}
          onTabChange={(tab) => updateDockState({ rightTab: tab })}
          selection={viewState.selection}
        />
      </div>

      {projectId && (
        <ColumnsModal
          projectId={projectId}
          isOpen={columnsModalOpen}
          onClose={() => setColumnsModalOpen(false)}
        />
      )}
    </div>
  )
}

export default GraphShell
