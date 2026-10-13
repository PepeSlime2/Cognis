import { Suspense, lazy } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, projectsQueryKey, type ProjectSummary } from '../../api/client'
import styles from './mainContent.module.css'

const GraphView = lazy(() => import('../Graph/GraphView'))

type MainContentProps = {
  projectId?: string
}

const MainContent = ({ projectId }: MainContentProps) => {
  const projectsQuery = useQuery({
    queryKey: projectsQueryKey,
    queryFn: () => api.get<ProjectSummary[]>('/projects'),
    enabled: !projectId,
  })

  if (projectId) {
    return (
      <Suspense fallback={<div className={styles.mainContentContainer}>Carregando grafo...</div>}>
        <GraphView projectId={projectId} />
      </Suspense>
    )
  }

  return (
    <div className={styles.pageContent}>
      <div className={styles.mainContentContainer}>
        <h2>Projetos</h2>
        {projectsQuery.isPending && <p>Carregando projetos...</p>}
        {projectsQuery.isError && (
          <p role="alert">Não foi possível carregar os projetos.</p>
        )}
        {projectsQuery.isSuccess && (
          <div className={styles.projectList}>
            {projectsQuery.data.length > 0 ? (
              projectsQuery.data.map((project) => (
                <article key={project.id} className={styles.projectCard}>
                  <strong>{project.name}</strong>
                  <p>{project.timezone} · {project.history_days} dias</p>
                </article>
              ))
            ) : (
              <p>Nenhum projeto encontrado. Crie um projeto nas configurações.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default MainContent
