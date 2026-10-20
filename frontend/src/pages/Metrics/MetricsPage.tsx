import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faCircleInfo,
  faDiagramProject,
  faChartSimple,
  faUsers,
  faWaveSquare,
  faArrowLeft,
} from '@fortawesome/free-solid-svg-icons'
import {
  api,
  type MetricCatalogEntry,
  type MetricsBundle,
} from '../../api/client'
import { WindowPicker } from '../../components/WindowPicker/WindowPicker'
import styles from './metricsPage.module.css'

export const MetricsPage = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [selectedWindow, setSelectedWindow] = useState('30d')
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null)

  const catalogQuery = useQuery({
    queryKey: ['metricsCatalog'],
    queryFn: () => api.get<MetricCatalogEntry[]>('/metrics/catalog'),
    staleTime: Infinity,
  })

  const metricsQuery = useQuery({
    queryKey: ['projectMetrics', projectId, selectedWindow],
    queryFn: () => {
      const params = new URLSearchParams()
      if (selectedWindow.startsWith('sprint:')) {
        params.set('sprint_id', selectedWindow.replace('sprint:', ''))
      } else {
        const days = parseInt(selectedWindow.replace('d', ''), 10) || 30
        const to = new Date()
        const from = new Date()
        from.setDate(to.getDate() - (days - 1))
        params.set('from', from.toISOString().split('T')[0])
        params.set('to', to.toISOString().split('T')[0])
      }
      return api.get<MetricsBundle>(`/projects/${projectId}/metrics?${params}`)
    },
    enabled: Boolean(projectId),
  })

  const catalogMap = new Map(catalogQuery.data?.map((item) => [item.id, item]))
  const metrics = metricsQuery.data?.metrics ?? {}

  const renderMetricCard = (metricId: string) => {
    const catalogInfo = catalogMap.get(metricId)
    const metricData = metrics[metricId]
    const title = catalogInfo?.name ?? metricId

    let displayValue: React.ReactNode = '—'
    let isInsufficient = false
    let reasonText = ''

    if (!metricData) {
      displayValue = <span style={{ color: '#64748b' }}>Carregando…</span>
    } else if (metricData.status === 'insufficient_data') {
      isInsufficient = true
      reasonText = metricData.reason ?? 'Dados insuficientes na janela'
    } else if (metricData.values !== null && metricData.values !== undefined) {
      if (typeof metricData.values === 'number') {
        displayValue = metricData.values.toFixed(2)
      } else if (typeof metricData.values === 'object') {
        if ('overall' in metricData.values) {
          displayValue = (Number(metricData.values.overall) * 100).toFixed(1) + '%'
        } else if ('median_days' in metricData.values) {
          displayValue = `${metricData.values.median_days}d`
        } else if ('median_h' in metricData.values) {
          displayValue = `${metricData.values.median_h}h`
        } else if ('late_rate' in metricData.values) {
          displayValue = (Number(metricData.values.late_rate) * 100).toFixed(1) + '%'
        } else if ('rework_rate' in metricData.values) {
          displayValue = (Number(metricData.values.rework_rate) * 100).toFixed(1) + '%'
        } else if ('count' in metricData.values) {
          displayValue = String(metricData.values.count)
        } else {
          // Média de valores por pessoa caso seja mapa
          const numValues = Object.values(metricData.values).filter(
            (v): v is number => typeof v === 'number',
          )
          if (numValues.length > 0) {
            const avg = numValues.reduce((a, b) => a + b, 0) / numValues.length
            displayValue = avg.toFixed(2)
          } else {
            displayValue = 'Ver detalhes'
          }
        }
      }
    }

    return (
      <div key={metricId} className={styles.card}>
        <div className={styles.cardHeader}>
          <span className={styles.cardTitle}>{title}</span>
          <button
            type="button"
            className={styles.infoIcon}
            onClick={() =>
              setActiveTooltip(activeTooltip === metricId ? null : metricId)
            }
            aria-label={`Ver detalhes de ${title}`}
            style={{ background: 'none', border: 'none' }}
          >
            <FontAwesomeIcon icon={faCircleInfo} />
          </button>
        </div>

        {activeTooltip === metricId && catalogInfo && (
          <div className={styles.tooltipBox}>
            <p>{catalogInfo.description}</p>
            <span className={styles.tooltipFormula}>Fórmula: {catalogInfo.formula}</span>
            <small style={{ display: 'block', marginTop: 4, color: '#94a3b8' }}>
              Amostra mínima: {catalogInfo.min_sample}
            </small>
          </div>
        )}

        <div className={styles.cardValueContainer}>
          {isInsufficient ? (
            <div>
              <span className={styles.insufficientBadge}>Dados insuficientes</span>
              <p className={styles.reasonText}>{reasonText}</p>
            </div>
          ) : (
            <div>
              <span className={styles.cardValue}>{displayValue}</span>
              {catalogInfo?.unit && catalogInfo.unit !== 'count' && (
                <span className={styles.cardUnit}>({catalogInfo.unit})</span>
              )}
            </div>
          )}
        </div>
      </div>
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
          <Link to={`/p/${projectId}/metrics`} className={`${styles.navLink} ${styles.navLinkActive}`}>
            <FontAwesomeIcon icon={faChartSimple} />
            <span>Métricas</span>
          </Link>
          <Link to={`/p/${projectId}/people`} className={styles.navLink}>
            <FontAwesomeIcon icon={faUsers} />
            <span>Equipe & Pessoas</span>
          </Link>
        </div>

        {projectId && (
          <WindowPicker
            projectId={projectId}
            windowVal={selectedWindow}
            onWindowChange={setSelectedWindow}
          />
        )}
      </header>

      <main className={styles.content}>
        <h1 className={styles.headerTitle}>Painel de Métricas do Projeto</h1>
        <p className={styles.subtitle}>
          Métricas determinísticas calculadas em Python puro sobre grafos de colaboração e eventos de fluxo.
        </p>

        {/* Categoria D: Fluxo e Risco */}
        <section className={styles.categorySection}>
          <h2 className={styles.categoryTitle}>
            <FontAwesomeIcon icon={faWaveSquare} style={{ color: '#60a5fa' }} />
            Fluxo e Risco do Projeto
          </h2>
          <div className={styles.grid}>
            {renderMetricCard('flow.completion_rate')}
            {renderMetricCard('flow.late_rate')}
            {renderMetricCard('flow.lead_time')}
            {renderMetricCard('flow.cycle_time')}
            {renderMetricCard('flow.rework')}
            {renderMetricCard('flow.pr_time_to_first_review')}
            {renderMetricCard('flow.pr_time_to_merge')}
            {renderMetricCard('flow.critical_dependencies')}
          </div>
        </section>

        {/* Categoria C: Colaboração e Estrutura */}
        <section className={styles.categorySection}>
          <h2 className={styles.categoryTitle}>
            <FontAwesomeIcon icon={faUsers} style={{ color: '#c084fc' }} />
            Colaboração e Estrutura da Equipe
          </h2>
          <div className={styles.grid}>
            {renderMetricCard('team.interaction_intensity')}
            {renderMetricCard('team.knowledge_concentration')}
            {renderMetricCard('team.activity_distribution')}
            {renderMetricCard('team.review_coverage')}
            {renderMetricCard('team.cross_community_share')}
          </div>
        </section>

        {/* Categoria A: Análise de Grafos */}
        <section className={styles.categorySection}>
          <h2 className={styles.categoryTitle}>
            <FontAwesomeIcon icon={faDiagramProject} style={{ color: '#34d399' }} />
            Estrutura e Topologia de Rede
          </h2>
          <div className={styles.grid}>
            {renderMetricCard('graph.density')}
            {renderMetricCard('graph.modularity')}
            {renderMetricCard('graph.components')}
            {renderMetricCard('graph.centralization')}
          </div>
        </section>

        <footer className={styles.footerNote}>
          Os indicadores descrevem padrões de colaboração e processo, não avaliam desempenho ou mérito individual.
        </footer>
      </main>
    </div>
  )
}
