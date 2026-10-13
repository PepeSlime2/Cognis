import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Core } from 'cytoscape'
import { useNavigate } from 'react-router-dom'
import {
  api,
  type GraphLayer,
  type GraphNodeData,
  type ProjectGraph,
  type ProjectSummary,
  type SyncRun,
  type SyncStartResponse,
} from '../../api/client'
import GraphCanvas from './GraphCanvas'
import styles from './graph.module.css'

type ProjectSource = {
  provider: 'github' | 'trello'
  external_id: string
  display_name: string | null
  enabled: boolean
}

type ProjectDetails = ProjectSummary & {
  sources: ProjectSource[]
}

const layers: Array<{ id: GraphLayer; label: string }> = [
  { id: 'all', label: 'Todos' },
  { id: 'people', label: 'Pessoas' },
  { id: 'tasks', label: 'Atividades' },
  { id: 'artifacts', label: 'Artefatos' },
]

const nodeTypeLabels: Record<string, string> = {
  person: 'Pessoa',
  task: 'Issue',
  pr: 'Pull request',
  commit: 'Commit',
  repo: 'Repositório',
  module: 'Módulo',
  column: 'Coluna',
}

const statusLabels: Record<SyncRun['status'], string> = {
  queued: 'Na fila',
  running: 'Em andamento',
  success: 'Concluída',
  partial: 'Concluída com falhas',
  failed: 'Falhou',
}

const GraphView = ({ projectId }: { projectId: string }) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [layer, setLayer] = useState<GraphLayer>('all')
  const [includeBots, setIncludeBots] = useState(false)
  const [minWeight, setMinWeight] = useState(1)
  const [search, setSearch] = useState('')
  const [labelsVisible, setLabelsVisible] = useState(true)
  const [selectedNode, setSelectedNode] = useState<GraphNodeData | null>(null)
  const [graph, setGraph] = useState<Core | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const autoSyncTriggeredRef = useRef(false)

  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get<ProjectDetails>(`/projects/${projectId}`),
  })
  const hasGithubSource = Boolean(
    projectQuery.data?.sources.some((source) => source.provider === 'github' && source.enabled),
  )
  const graphQuery = useQuery({
    queryKey: ['projectGraph', projectId, layer, includeBots, minWeight],
    queryFn: () => {
      const params = new URLSearchParams({
        layer,
        max_nodes: '400',
        min_weight: String(minWeight),
        include_bots: String(includeBots),
      })
      return api.get<ProjectGraph>(`/projects/${projectId}/graph?${params}`)
    },
    enabled: hasGithubSource,
  })
  const syncMutation = useMutation({
    mutationFn: () => api.post<SyncStartResponse>(`/projects/${projectId}/sync`),
    onSuccess: async (run) => {
      setRunId(run.run_id)
      await queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] })
    },
  })
  const runQuery = useQuery({
    queryKey: ['projectSyncRun', projectId, runId],
    queryFn: () => api.get<SyncRun>(`/projects/${projectId}/sync-runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1000 : false
    },
  })

  useEffect(() => {
    const status = runQuery.data?.status
    if (status && status !== 'queued' && status !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    }
  }, [projectId, queryClient, runQuery.data?.status])

  const onGraphReady = useCallback((instance: Core | null) => {
    setGraph(instance)
  }, [])
  const handleLayerChange = (nextLayer: GraphLayer) => {
    setLayer(nextLayer)
    setSelectedNode(null)
  }
  const activeRun = runQuery.data?.status === 'queued' || runQuery.data?.status === 'running'
  const syncInProgress = syncMutation.isPending || activeRun

  useEffect(() => {
    autoSyncTriggeredRef.current = false
  }, [projectId])

  useEffect(() => {
    if (
      !hasGithubSource ||
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
  }, [graphQuery.data?.stats.nodes, graphQuery.isFetching, graphQuery.isSuccess, hasGithubSource, syncInProgress, syncMutation])
  const graphNodes = graphQuery.data?.elements.nodes
  const isEmpty = graphQuery.isSuccess && graphNodes?.length === 0
  const detailEntries = useMemo(() => {
    if (!selectedNode) return []
    return Object.entries(selectedNode.metrics).filter(([, value]) => Number.isFinite(value))
  }, [selectedNode])

  const focusSearchResult = () => {
    const term = search.trim().toLocaleLowerCase('pt-BR')
    if (!graph || !term) return
    const match = graph.nodes().filter((node) =>
      String(node.data('label')).toLocaleLowerCase('pt-BR').includes(term),
    ).first()
    if (match.empty()) return
    graph.animate({ center: { eles: match }, zoom: 1.2, duration: 250 })
    match.select()
    setSelectedNode(match.data() as GraphNodeData)
  }

  const runLayout = () => {
    graph?.layout({
      name: 'fcose',
      quality: 'default',
      animate: true,
      randomize: true,
      fit: true,
      padding: 44,
      nodeRepulsion: 4500,
      idealEdgeLength: 120,
      numIter: 2500,
    }).run()
  }

  const exportPng = () => {
    if (!graph) return
    const image = graph.png({
      output: 'base64uri',
      bg: '#02001b',
      full: true,
      scale: 2,
    })
    const anchor = document.createElement('a')
    anchor.href = image
    anchor.download = 'cognis-grafo.png'
    anchor.click()
  }

  const toggleLabels = () => {
    const nextVisibility = !labelsVisible
    setLabelsVisible(nextVisibility)
    graph?.nodes().style('label', nextVisibility ? 'data(label)' : '')
  }

  if (projectQuery.isPending) {
    return <section className={styles.page}><p>Carregando projeto...</p></section>
  }
  if (projectQuery.isError || !projectQuery.data) {
    return (
      <section className={styles.page}>
        <div className={styles.stateCard} role="alert">
          <h2>Não foi possível carregar este projeto</h2>
          <p>{projectQuery.error instanceof Error ? projectQuery.error.message : 'Tente novamente.'}</p>
          <button type="button" onClick={() => void projectQuery.refetch()}>Tentar novamente</button>
        </div>
      </section>
    )
  }

  return (
    <section className={styles.page}>
      <header className={styles.heading}>
        <div>
          <p className={styles.eyebrow}>VISUALIZAÇÃO DO PROJETO</p>
          <h1>{projectQuery.data.name}</h1>
          <p className={styles.subtitle}>
            Relações e atividade dos repositórios GitHub conectados
          </p>
        </div>
        <button
          className={styles.syncButton}
          type="button"
          onClick={() => syncMutation.mutate()}
          disabled={!hasGithubSource || syncInProgress}
        >
          {syncInProgress ? 'Sincronizando…' : 'Sincronizar GitHub'}
        </button>
      </header>

      {!hasGithubSource ? (
        <div className={styles.stateCard}>
          <h2>Nenhum repositório GitHub conectado a este projeto</h2>
          <p>Adicione uma fonte GitHub nas configurações do projeto para carregar o grafo.</p>
          <button type="button" onClick={() => navigate('/settings')}>Abrir configurações</button>
        </div>
      ) : (
        <>
          <div className={styles.toolbar}>
            <div className={styles.layerTabs} aria-label="Camadas do grafo">
              {layers.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={layer === item.id ? styles.activeLayer : ''}
                  aria-pressed={layer === item.id}
                  onClick={() => handleLayerChange(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <form
              className={styles.searchForm}
              onSubmit={(event) => {
                event.preventDefault()
                focusSearchResult()
              }}
            >
              <input
                aria-label="Buscar nó no grafo"
                placeholder="Buscar pessoa, issue ou repositório"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <button type="submit" disabled={!graph}>Buscar</button>
            </form>
            <label className={styles.weightFilter}>
              Peso mínimo
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={minWeight}
                onChange={(event) => {
                  setMinWeight(Number(event.target.value))
                  setSelectedNode(null)
                }}
              />
              <output>{minWeight}+</output>
            </label>
            <label className={styles.botFilter}>
              <input
                type="checkbox"
                checked={includeBots}
                onChange={(event) => {
                  setIncludeBots(event.target.checked)
                  setSelectedNode(null)
                }}
              />
              Incluir bots
            </label>
          </div>

          {syncMutation.isError && (
            <p className={styles.errorBanner} role="alert">
              {syncMutation.error instanceof Error
                ? syncMutation.error.message
                : 'Não foi possível iniciar a sincronização.'}
            </p>
          )}
          {runQuery.isError && (
            <p className={styles.errorBanner} role="alert">
              Não foi possível consultar o estado da sincronização.
            </p>
          )}
          {runQuery.data && (
            <div className={styles.runStatus} role="status">
              <strong>{statusLabels[runQuery.data.status]}</strong>
              <span>{runQuery.data.progress.message}</span>
              {runQuery.data.progress.total !== undefined && (
                <span>{runQuery.data.progress.done ?? 0}/{runQuery.data.progress.total} repositórios</span>
              )}
              {runQuery.data.errors.map((error, index) => (
                <span className={styles.runError} key={`${error.code ?? 'error'}-${index}`}>
                  {error.message}
                </span>
              ))}
            </div>
          )}
          {graphQuery.isError && (
            <p className={styles.errorBanner} role="alert">
              {graphQuery.error instanceof Error
                ? graphQuery.error.message
                : 'Não foi possível carregar o grafo.'}
              <button type="button" onClick={() => void graphQuery.refetch()}>Tentar novamente</button>
            </p>
          )}

          <div className={styles.summaryBar}>
            <span>{graphQuery.data?.stats.nodes ?? 0} nós</span>
            <span>{graphQuery.data?.stats.edges ?? 0} relações</span>
            {graphQuery.isFetching && <span>Atualizando…</span>}
            {graphQuery.data?.truncated && (
              <span className={styles.truncatedNotice}>
                Visualização limitada a 400 nós e 1.500 relações
              </span>
            )}
            <div className={styles.graphActions}>
              <button type="button" onClick={() => graph?.fit()} disabled={!graph}>Enquadrar</button>
              <button type="button" onClick={runLayout} disabled={!graph}>Reorganizar</button>
              <button type="button" onClick={toggleLabels} disabled={!graph}>
                {labelsVisible ? 'Ocultar rótulos' : 'Mostrar rótulos'}
              </button>
              <button type="button" onClick={exportPng} disabled={!graph}>Exportar PNG</button>
            </div>
          </div>

          {graphQuery.isPending ? (
            <div className={styles.stateCard}><p>Carregando grafo...</p></div>
          ) : isEmpty ? (
            <div className={styles.stateCard}>
              <h2>O grafo ainda está vazio</h2>
              <p>Sincronize os repositórios para carregar commits, issues e pull requests.</p>
              <button
                className={styles.syncButton}
                type="button"
                onClick={() => syncMutation.mutate()}
                disabled={syncInProgress}
              >
                {syncInProgress ? 'Sincronizando…' : 'Sincronizar agora'}
              </button>
            </div>
          ) : graphQuery.data ? (
            <div className={styles.visualization}>
              <div className={styles.canvasPanel}>
                <GraphCanvas
                  elements={graphQuery.data.elements}
                  labelsVisible={labelsVisible}
                  onNodeSelect={setSelectedNode}
                  onGraphReady={onGraphReady}
                />
                <div className={styles.legend} aria-label="Legenda do grafo">
                  <span><i className={styles.personColor} /> Pessoas</span>
                  <span><i className={styles.taskColor} /> Issues</span>
                  <span><i className={styles.prColor} /> Pull requests</span>
                  <span><i className={styles.repoColor} /> Repositórios</span>
                  <span><i className={styles.moduleColor} /> Módulos</span>
                </div>
              </div>
              <aside className={styles.detailsPanel} aria-live="polite">
                {selectedNode ? (
                  <>
                    <p className={styles.eyebrow}>DETALHES DO NÓ</p>
                    <h2>{selectedNode.label}</h2>
                    <span className={styles.nodeType}>
                      {nodeTypeLabels[selectedNode.type] ?? selectedNode.type}
                    </span>
                    {selectedNode.status_category && (
                      <p>Status: {selectedNode.status_category}</p>
                    )}
                    {selectedNode.flags.map((flag) => (
                      <span className={styles.flag} key={flag}>{flag === 'bot' ? 'Bot' : flag}</span>
                    ))}
                    {detailEntries.map(([name, value]) => (
                      <p key={name}>{name}: {value}</p>
                    ))}
                    {selectedNode.url && (
                      <a href={selectedNode.url} target="_blank" rel="noreferrer">
                        Abrir no GitHub
                      </a>
                    )}
                  </>
                ) : (
                  <p>Selecione um nó para ver seus detalhes.</p>
                )}
              </aside>
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}

export default GraphView
