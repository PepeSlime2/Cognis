import { Suspense, lazy } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, projectsQueryKey, type ProjectSummary } from '../../api/client'
import styles from './mainContent.module.css'

const GraphView = lazy(() => import('../Graph/GraphView'))

type MainContentProps = {
  projectId?: string
}

const MainContent = ({ projectId }: MainContentProps) => {
  const navigate = useNavigate()
  const projectsQuery = useQuery({
    queryKey: projectsQueryKey,
    queryFn: () => api.get<ProjectSummary[]>('/projects'),
    enabled: !projectId,
  })

  if (projectId) {
    return (
      <Suspense fallback={<div className={styles.loadingContainer}><p>Carregando grafo do projeto...</p></div>}>
        <GraphView projectId={projectId} />
      </Suspense>
    )
  }

  return (
    <div className={styles.pageContent}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>VISÃO GERAL</span>
          <h1>Seus Projetos</h1>
          <p className={styles.subtitle}>
            Selecione um projeto para visualizar seu grafo de colaboração, métricas e análises.
          </p>
        </div>
        <button
          type="button"
          className={styles.newProjectButton}
          onClick={() => navigate('/settings')}
        >
          Gerenciar Projetos
        </button>
      </header>

      <div className={styles.mainContentContainer}>
        {projectsQuery.isPending && (
          <div className={styles.loadingContainer}>
            <p>Carregando projetos...</p>
          </div>
        )}
        {projectsQuery.isError && (
          <div className={styles.errorContainer} role="alert">
            <p>Não foi possível carregar os projetos.</p>
            <button type="button" onClick={() => void projectsQuery.refetch()}>
              Tentar novamente
            </button>
          </div>
        )}
        {projectsQuery.isSuccess && (
          <>
            {projectsQuery.data.length > 0 ? (
              <div className={styles.projectList}>
                {projectsQuery.data.map((project) => (
                  <article
                    key={project.id}
                    className={styles.projectCard}
                    onClick={() => navigate(`/p/${project.id}`)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        navigate(`/p/${project.id}`)
                      }
                    }}
                  >
                    <div className={styles.projectCardHeader}>
                      <span className={styles.projectIcon} />
                      <strong>{project.name}</strong>
                    </div>
                    <div className={styles.projectDetails}>
                      <span>{project.timezone}</span>
                      <span>·</span>
                      <span>{project.history_days} dias de histórico</span>
                    </div>
                    <div className={styles.projectActionRow}>
                      <span className={styles.openProjectLink}>Abrir Grafo →</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className={styles.emptyContainer}>
                <h3>Nenhum projeto encontrado</h3>
                <p>Crie um projeto nas configurações para conectar repositórios e quadros.</p>
                <button
                  type="button"
                  className={styles.newProjectButton}
                  onClick={() => navigate('/settings')}
                >
                  Criar primeiro projeto
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default MainContent
