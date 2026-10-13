import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import styles from './settingsPage.module.css'
import {
  ApiError,
  api,
  projectsQueryKey,
  sessionQueryKey,
  type ProjectSummary,
  type SessionResponse,
} from '../../api/client'

type ProjectSource = {
  provider: 'github' | 'trello'
  external_id: string
  display_name: string
  enabled: boolean
}

type ProjectDetails = ProjectSummary & {
  sources: ProjectSource[]
}

type GithubRepo = {
  full_name: string
  private: boolean
}

type TrelloBoard = {
  id: string
  name: string
}

type SourceSelection = {
  github: string[]
  trello: string[]
}

function SettingsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedProjectId = searchParams.get('project') ?? ''
  const [projectName, setProjectName] = useState('')
  const [sourceSelections, setSourceSelections] = useState<Record<string, SourceSelection>>({})
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState(false)
  const [connectingProvider, setConnectingProvider] = useState<'github' | 'trello' | null>(null)

  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => api.get<SessionResponse>('/auth/me'),
  })
  const projectsQuery = useQuery({
    queryKey: projectsQueryKey,
    queryFn: () => api.get<ProjectSummary[]>('/projects'),
  })
  const projectQuery = useQuery({
    queryKey: ['project', selectedProjectId],
    queryFn: () => api.get<ProjectDetails>(`/projects/${selectedProjectId}`),
    enabled: Boolean(selectedProjectId),
  })
  const reposQuery = useQuery({
    queryKey: ['github', 'repos'],
    queryFn: () => api.get<GithubRepo[]>('/github/repos'),
    enabled: Boolean(selectedProjectId && sessionQuery.data?.connections.github),
  })
  const boardsQuery = useQuery({
    queryKey: ['trello', 'boards'],
    queryFn: () => api.get<TrelloBoard[]>('/trello/boards'),
    enabled: Boolean(selectedProjectId && sessionQuery.data?.connections.trello),
  })

  if (sessionQuery.isPending) {
    return <main className={styles.page}><p>Carregando configurações...</p></main>
  }
  if (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
    return <Navigate to="/login" replace />
  }
  if (sessionQuery.isError) {
    return (
      <main className={styles.page}>
        <h1>Não foi possível carregar sua sessão</h1>
        <p role="alert">{sessionQuery.error.message}</p>
        <button type="button" onClick={() => void sessionQuery.refetch()}>Tentar novamente</button>
      </main>
    )
  }

  const createProject = async () => {
    setError('')
    setSuccess('')
    if (!projectName.trim()) {
      setError('Informe um nome para o projeto.')
      return
    }

    setSaving(true)
    try {
      const project = await api.post<ProjectSummary>('/projects', {
        name: projectName.trim(),
        timezone: 'America/Sao_Paulo',
        history_days: 90,
        auto_sync: false,
        sync_interval_min: 60,
      })
      setProjectName('')
      await queryClient.invalidateQueries({ queryKey: projectsQueryKey })
      setSearchParams({ project: project.id })
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Não foi possível criar o projeto.')
    } finally {
      setSaving(false)
    }
  }

  const persistedSelection: SourceSelection = projectQuery.data?.id === selectedProjectId
    ? {
        github: projectQuery.data.sources
          .filter((source) => source.provider === 'github' && source.enabled)
          .map((source) => source.external_id),
        trello: projectQuery.data.sources
          .filter((source) => source.provider === 'trello' && source.enabled)
          .map((source) => source.external_id),
      }
    : { github: [], trello: [] }
  const activeSelection = sourceSelections[selectedProjectId] ?? persistedSelection
  const sourceCount = activeSelection.github.length + activeSelection.trello.length

  const toggleSelection = (provider: keyof SourceSelection, id: string) => {
    setSourceSelections((previous) => {
      const current = previous[selectedProjectId] ?? persistedSelection
      const selected = current[provider]
      return {
        ...previous,
        [selectedProjectId]: {
          ...current,
          [provider]: selected.includes(id)
            ? selected.filter((item) => item !== id)
            : [...selected, id],
        },
      }
    })
  }

  const connectProvider = async (provider: 'github' | 'trello') => {
    setError('')
    setSuccess('')
    setConnectingProvider(provider)

    try {
      const authorizePath =
        provider === 'github' ? '/auth/github/login' : '/auth/trello/authorize-url'
      const payload = await api.get<{ authorize_url: string }>(authorizePath)
      window.location.href = payload.authorize_url
    } catch (requestError) {
      setConnectingProvider(null)
      setError(
        requestError instanceof Error
          ? requestError.message
          : `Não foi possível conectar ao ${provider === 'github' ? 'GitHub' : 'Trello'}.`,
      )
    }
  }

  const saveSources = async () => {
    if (!selectedProjectId) return
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      await api.put<ProjectDetails>(`/projects/${selectedProjectId}/sources`, {
        github_repos: activeSelection.github,
        trello_boards: activeSelection.trello,
      })
      await queryClient.invalidateQueries({ queryKey: ['project', selectedProjectId] })
      setSuccess('Fontes do projeto salvas.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Não foi possível salvar as fontes.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>COGNIS · CONFIGURAÇÕES</p>
          <h1>Projetos e fontes</h1>
          <p className={styles.subtitle}>
            Olá, {sessionQuery.data.name || sessionQuery.data.email || 'Usuário'}. Gerencie os projetos que alimentam seu grafo.
          </p>
        </div>
        <button className={styles.secondaryButton} onClick={() => navigate('/')} type="button">
          Voltar ao início
        </button>
      </header>

      {error && <p className={styles.error} role="alert">{error}</p>}
      {success && <p className={styles.success} role="status">{success}</p>}

      <section className={styles.panel}>
        <h2>Criar projeto</h2>
        <p className={styles.helper}>Cada projeto mantém suas próprias fontes e dados.</p>
        <form
          className={styles.createForm}
          onSubmit={(event) => {
            event.preventDefault()
            void createProject()
          }}
        >
          <label className={styles.visuallyHidden} htmlFor="new-project-name">Nome do projeto</label>
          <input
            id="new-project-name"
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
            placeholder="Ex.: Equipe de produto"
            maxLength={80}
          />
          <button className={styles.primaryButton} disabled={saving} type="submit">
            {saving ? 'Salvando...' : 'Criar projeto'}
          </button>
        </form>
      </section>

      <section className={styles.panel}>
        <div className={styles.sectionHeader}>
          <div>
            <h2>Projetos</h2>
            <p className={styles.helper}>Selecione um projeto para configurar suas fontes.</p>
          </div>
          {selectedProjectId && projectsQuery.data && (
            <label className={styles.projectPicker}>
              Projeto selecionado
              <select
                value={selectedProjectId}
                onChange={(event) => setSearchParams(event.target.value ? { project: event.target.value } : {})}
              >
                {projectsQuery.data.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        {projectsQuery.isPending && <p>Carregando projetos...</p>}
        {projectsQuery.isError && (
          <div className={styles.errorBlock} role="alert">
            <p>Não foi possível carregar os projetos.</p>
            <button className={styles.secondaryButton} onClick={() => void projectsQuery.refetch()} type="button">
              Tentar novamente
            </button>
          </div>
        )}
        {!projectsQuery.isPending && !projectsQuery.isError && projectsQuery.data.length === 0 && (
          <p className={styles.emptyState}>Nenhum projeto criado ainda.</p>
        )}
        {!projectsQuery.isPending && !projectsQuery.isError && projectsQuery.data.length > 0 && (
          <div className={styles.projectList}>
            {projectsQuery.data.map((project) => (
              <button
                className={`${styles.projectCard} ${project.id === selectedProjectId ? styles.selectedProject : ''}`}
                key={project.id}
                onClick={() => setSearchParams({ project: project.id })}
                type="button"
              >
                <span className={styles.projectName}>{project.name}</span>
                <span className={styles.projectMeta}>
                  {project.timezone} · {project.history_days} dias de histórico
                </span>
                <span className={styles.projectMeta}>
                  Sincronização {project.auto_sync ? 'automática' : 'manual'}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      {selectedProjectId && (
        <section className={styles.panel}>
          <div className={styles.sectionHeader}>
            <div>
              <h2>Fontes de dados</h2>
              <p className={styles.helper}>Escolha repositórios e boards reais aos quais suas conexões têm acesso.</p>
            </div>
            <span className={styles.counter}>{sourceCount}/20 fontes</span>
          </div>

          {projectQuery.isPending && <p>Carregando fontes do projeto...</p>}
          {projectQuery.isError && (
            <div className={styles.errorBlock} role="alert">
              <p>Não foi possível carregar este projeto.</p>
              <button className={styles.secondaryButton} onClick={() => void projectQuery.refetch()} type="button">
                Tentar novamente
              </button>
            </div>
          )}
          {projectQuery.data && (
            <>
              <div className={styles.sourceColumns}>
                <fieldset className={styles.sourceGroup}>
                  <legend>GitHub</legend>
                  {!sessionQuery.data.connections.github && (
                    <div className={styles.providerActionRow}>
                      <p className={styles.emptyState}>Conecte o GitHub para listar os repositórios do projeto.</p>
                      <button
                        className={styles.secondaryButton}
                        disabled={connectingProvider !== null}
                        onClick={() => void connectProvider('github')}
                        type="button"
                      >
                        {connectingProvider === 'github' ? 'Redirecionando...' : 'Conectar GitHub'}
                      </button>
                    </div>
                  )}
                  {sessionQuery.data.connections.github && reposQuery.isPending && <p>Carregando repositórios...</p>}
                  {sessionQuery.data.connections.github && reposQuery.isError && (
                    <div className={styles.errorBlock} role="alert">
                      <p>Não foi possível carregar os repositórios.</p>
                      <button className={styles.secondaryButton} onClick={() => void reposQuery.refetch()} type="button">
                        Tentar novamente
                      </button>
                    </div>
                  )}
                  {reposQuery.data?.length === 0 && <p className={styles.emptyState}>Nenhum repositório disponível.</p>}
                  {reposQuery.data?.map((repo) => (
                    <label className={styles.sourceOption} key={repo.full_name}>
                      <input
                        checked={activeSelection.github.includes(repo.full_name)}
                        disabled={!activeSelection.github.includes(repo.full_name) && sourceCount >= 20}
                        onChange={() => toggleSelection('github', repo.full_name)}
                        type="checkbox"
                      />
                      <span>{repo.full_name}{repo.private ? ' · privado' : ''}</span>
                    </label>
                  ))}
                </fieldset>

                <fieldset className={styles.sourceGroup}>
                  <legend>Trello</legend>
                  {!sessionQuery.data.connections.trello && (
                    <div className={styles.providerActionRow}>
                      <p className={styles.emptyState}>Conecte o Trello para listar os boards do projeto.</p>
                      <button
                        className={styles.secondaryButton}
                        disabled={connectingProvider !== null}
                        onClick={() => void connectProvider('trello')}
                        type="button"
                      >
                        {connectingProvider === 'trello' ? 'Redirecionando...' : 'Conectar Trello'}
                      </button>
                    </div>
                  )}
                  {sessionQuery.data.connections.trello && boardsQuery.isPending && <p>Carregando boards...</p>}
                  {sessionQuery.data.connections.trello && boardsQuery.isError && (
                    <div className={styles.errorBlock} role="alert">
                      <p>Não foi possível carregar os boards.</p>
                      <button className={styles.secondaryButton} onClick={() => void boardsQuery.refetch()} type="button">
                        Tentar novamente
                      </button>
                    </div>
                  )}
                  {boardsQuery.data?.length === 0 && <p className={styles.emptyState}>Nenhum board disponível.</p>}
                  {boardsQuery.data?.map((board) => (
                    <label className={styles.sourceOption} key={board.id}>
                      <input
                        checked={activeSelection.trello.includes(board.id)}
                        disabled={!activeSelection.trello.includes(board.id) && sourceCount >= 20}
                        onChange={() => toggleSelection('trello', board.id)}
                        type="checkbox"
                      />
                      <span>{board.name}</span>
                    </label>
                  ))}
                </fieldset>
              </div>
              <div className={styles.saveRow}>
                <button className={styles.primaryButton} disabled={saving || projectQuery.isPending} onClick={() => void saveSources()} type="button">
                  {saving ? 'Salvando...' : 'Salvar fontes'}
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </main>
  )
}

export default SettingsPage
