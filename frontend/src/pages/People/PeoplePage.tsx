import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faDiagramProject,
  faChartSimple,
  faUsers,
  faArrowLeft,
  faCircleInfo,
} from '@fortawesome/free-solid-svg-icons'
import {
  api,
  type MetricCatalogEntry,
  type MetricsBundle,
  type PeopleResponse,
} from '../../api/client'
import styles from './peoplePage.module.css'

export const PeoplePage = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [activeHeaderTooltip, setActiveHeaderTooltip] = useState<string | null>(null)

  const peopleQuery = useQuery({
    queryKey: ['projectPeople', projectId],
    queryFn: () => api.get<PeopleResponse>(`/projects/${projectId}/people`),
    enabled: Boolean(projectId),
  })

  const catalogQuery = useQuery({
    queryKey: ['metricsCatalog'],
    queryFn: () => api.get<MetricCatalogEntry[]>('/metrics/catalog'),
    staleTime: Infinity,
  })

  const metricsQuery = useQuery({
    queryKey: ['projectMetrics', projectId, '30d'],
    queryFn: () => {
      const to = new Date()
      const from = new Date()
      from.setDate(to.getDate() - 29)
      const params = new URLSearchParams({
        from: from.toISOString().split('T')[0],
        to: to.toISOString().split('T')[0],
      })
      return api.get<MetricsBundle>(`/projects/${projectId}/metrics?${params}`)
    },
    enabled: Boolean(projectId),
  })

  const catalogMap = new Map(catalogQuery.data?.map((m) => [m.id, m]))
  const metrics = metricsQuery.data?.metrics ?? {}

  const counters = (metrics['person.counters']?.values ?? {}) as Record<string, Record<string, number>>
  const participation = (metrics['person.participation']?.values ?? {}) as Record<string, number | null>
  const collaboration = (metrics['person.collaboration']?.values ?? {}) as Record<string, number | null>
  const delivery = (metrics['person.delivery']?.values ?? {}) as Record<string, number | null>
  const quality = (metrics['person.quality']?.values ?? {}) as Record<string, number | null>
  const overall = (metrics['person.overall']?.values ?? {}) as Record<
    string,
    { overall: number | null; used_components?: string[] } | number | null
  >

  // Lista de pessoas sem ordenação por ranking (alfabética por padrão)
  const people = [...(peopleQuery.data?.people ?? [])]
    .filter((p) => !p.excluded)
    .sort((a, b) => (a.display_name ?? '').localeCompare(b.display_name ?? ''))

  const renderScore = (score: unknown) => {
    const val =
      typeof score === 'number'
        ? score
        : typeof score === 'string' && score.trim() !== '' && !Number.isNaN(Number(score))
        ? Number(score)
        : null
    if (val === null || Number.isNaN(val)) {
      return <span className={styles.nullBadge}>N/A</span>
    }
    return <span className={styles.scoreBadge}>{val.toFixed(1)}</span>
  }

  const renderHeaderWithTooltip = (id: string, title: string) => {
    const info = catalogMap.get(id)
    return (
      <th key={id}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>{title}</span>
          {info && (
            <button
              type="button"
              onClick={() => setActiveHeaderTooltip(activeHeaderTooltip === id ? null : id)}
              style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}
              aria-label={`Ver fórmula de ${title}`}
            >
              <FontAwesomeIcon icon={faCircleInfo} />
            </button>
          )}
        </div>
        {activeHeaderTooltip === id && info && (
          <div
            style={{
              position: 'absolute',
              background: '#0f0b29',
              border: '1px solid #8b5cf6',
              padding: 10,
              borderRadius: 6,
              fontSize: 11,
              maxWidth: 240,
              textTransform: 'none',
              zIndex: 40,
              boxShadow: '0 8px 20px rgba(0,0,0,0.5)',
            }}
          >
            <p>{info.description}</p>
            <span style={{ color: '#c084fc', fontFamily: 'monospace', display: 'block', marginTop: 4 }}>
              {info.formula}
            </span>
          </div>
        )}
      </th>
    )
  }

  return (
    <div className={styles.container}>
      <header className={styles.topBar}>
        <div className={styles.navLinks}>
          <Link to={`/p/${projectId}`} className={styles.navLink}>
            <FontAwesomeIcon icon={faArrowLeft} />
            <span>Voltar ao Grafo</span>
          </Link>
          <span style={{ color: 'rgba(255,255,255,0.2)' }}>|</span>
          <Link to={`/p/${projectId}`} className={styles.navLink}>
            <FontAwesomeIcon icon={faDiagramProject} />
            <span>Grafo</span>
          </Link>
          <Link to={`/p/${projectId}/metrics`} className={styles.navLink}>
            <FontAwesomeIcon icon={faChartSimple} />
            <span>Métricas</span>
          </Link>
          <Link to={`/p/${projectId}/people`} className={`${styles.navLink} ${styles.navLinkActive}`}>
            <FontAwesomeIcon icon={faUsers} />
            <span>Equipe & Pessoas</span>
          </Link>
        </div>
      </header>

      <main className={styles.content}>
        <h1 className={styles.headerTitle}>Colaboradores e Índices da Equipe</h1>
        <p className={styles.subtitle}>
          Visualização transparente e equilibrada dos índices e contadores de atividade na janela temporal (30 dias).
        </p>

        {peopleQuery.isLoading ? (
          <div className={styles.stateCard} aria-busy="true">
            <p className={styles.stateTitle}>Carregando colaboradores...</p>
            <p>Calculando índices e contadores de colaboração da equipe.</p>
          </div>
        ) : peopleQuery.isError ? (
          <div className={styles.errorCard} role="alert">
            <p className={styles.errorTitle}>Não foi possível carregar os colaboradores</p>
            <p>{peopleQuery.error instanceof Error ? peopleQuery.error.message : 'Erro ao consultar a lista de pessoas.'}</p>
            <button
              type="button"
              className={styles.retryBtn}
              onClick={() => void peopleQuery.refetch()}
            >
              Tentar novamente
            </button>
          </div>
        ) : people.length === 0 ? (
          <div className={styles.stateCard}>
            <p className={styles.stateTitle}>Nenhum colaborador encontrado</p>
            <p>Conecte repositórios ou quadros ao projeto e execute a sincronização para carregar as pessoas da equipe.</p>
            <Link to={`/p/${projectId}`} className={styles.retryBtn} style={{ display: 'inline-block', textDecoration: 'none' }}>
              Voltar ao Projeto
            </Link>
          </div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Colaborador</th>
                  <th scope="col">Commits</th>
                  <th scope="col">PRs</th>
                  <th scope="col">Reviews</th>
                  <th scope="col">Tarefas Concluídas</th>
                  {renderHeaderWithTooltip('person.participation', 'Participação')}
                  {renderHeaderWithTooltip('person.collaboration', 'Colaboração')}
                  {renderHeaderWithTooltip('person.delivery', 'Entrega')}
                  {renderHeaderWithTooltip('person.quality', 'Qualidade (Proxy)')}
                  {renderHeaderWithTooltip('person.overall', 'Score Global')}
                </tr>
              </thead>
              <tbody>
                {people.map((person) => {
                  const uid = person.person_uid
                  const personCounters = counters[uid] ?? {}
                  const personOverall = overall[uid]
                  const overallVal =
                    typeof personOverall === 'object' && personOverall !== null
                      ? personOverall.overall
                      : typeof personOverall === 'number'
                      ? personOverall
                      : null

                  const nameStr = person.display_name?.trim() || 'User'
                  const initials =
                    nameStr
                      .split(/\s+/)
                      .filter(Boolean)
                      .map((w) => w[0])
                      .slice(0, 2)
                      .join('')
                      .toUpperCase() || 'U'

                  return (
                    <tr key={uid}>
                      <td>
                        <div className={styles.personCell}>
                          <div className={styles.avatarCircle}>{initials}</div>
                          <span>{person.display_name ?? uid}</span>
                        </div>
                      </td>
                      <td>{personCounters.commits ?? 0}</td>
                      <td>{personCounters.prs_opened ?? 0}</td>
                      <td>{personCounters.reviews_given ?? 0}</td>
                      <td>{personCounters.tasks_done ?? 0}</td>
                      <td>{renderScore(participation[uid])}</td>
                      <td>{renderScore(collaboration[uid])}</td>
                      <td>{renderScore(delivery[uid])}</td>
                      <td>{renderScore(quality[uid])}</td>
                      <td>{renderScore(overallVal)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <footer className={styles.footerNote}>
          Os indicadores descrevem padrões de colaboração e processo, não avaliam desempenho ou mérito individual.
        </footer>
      </main>
    </div>
  )
}
