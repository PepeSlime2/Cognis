import { useState, useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faChartLine,
  faTriangleExclamation,
  faArrowTrendDown,
  faArrowTrendUp,
  faCircle,
  faEye,
} from '@fortawesome/free-solid-svg-icons'
import {
  evolutionApi,
  type EvolutionPeriod,
  type TeamEvolutionResult,
} from '../../api/client'
import styles from './evolutionChart.module.css'

type MetricOption = {
  key: keyof Pick<
    EvolutionPeriod,
    | 'weight_per_person'
    | 'density'
    | 'modularity'
    | 'centralization'
    | 'active_people_count'
    | 'reviews_per_pr'
  >
  label: string
  format: (v: number) => string
  unit: string
}

const METRIC_OPTIONS: MetricOption[] = [
  {
    key: 'weight_per_person',
    label: 'Intensidade de Colaboração (peso/pessoa)',
    format: (v) => v.toFixed(2),
    unit: 'peso',
  },
  {
    key: 'density',
    label: 'Densidade da Rede',
    format: (v) => (v * 100).toFixed(1) + '%',
    unit: 'ratio',
  },
  {
    key: 'modularity',
    label: 'Modularidade (Comunidades / Silos)',
    format: (v) => v.toFixed(3),
    unit: '',
  },
  {
    key: 'centralization',
    label: 'Centralização de Freeman',
    format: (v) => (v * 100).toFixed(1) + '%',
    unit: 'ratio',
  },
  {
    key: 'active_people_count',
    label: 'Pessoas Ativas',
    format: (v) => Math.round(v).toString(),
    unit: 'pessoas',
  },
  {
    key: 'reviews_per_pr',
    label: 'Reviews por PR',
    format: (v) => v.toFixed(2),
    unit: 'rev/pr',
  },
]

type EvolutionChartProps = {
  projectId: string
  onSelectPeriod?: (periodWindowParam: string) => void
}

export const EvolutionChart = ({ projectId, onSelectPeriod }: EvolutionChartProps) => {
  const gradientId = useId()
  const [granularity, setGranularity] = useState<'sprint' | '14d'>('sprint')
  const [selectedMetricKey, setSelectedMetricKey] = useState<MetricOption['key']>(
    'weight_per_person',
  )
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  const {
    data: evolutionResult,
    isLoading,
    isError,
    refetch,
  } = useQuery<TeamEvolutionResult>({
    queryKey: ['teamEvolution', projectId, granularity],
    queryFn: () => evolutionApi.getEvolution(projectId, granularity),
    enabled: Boolean(projectId),
  })

  const selectedMetric =
    METRIC_OPTIONS.find((m) => m.key === selectedMetricKey) ?? METRIC_OPTIONS[0]

  if (isLoading) {
    return (
      <div className={styles.evolutionContainer}>
        <div className={styles.stateBox}>
          <div className={styles.spinner} />
          <p>Carregando evolução temporal da equipe…</p>
        </div>
      </div>
    )
  }

  if (isError || !evolutionResult) {
    return (
      <div className={styles.evolutionContainer}>
        <div className={styles.stateBox}>
          <p>Não foi possível carregar a série de evolução temporal.</p>
          <button
            type="button"
            className={styles.actionBtn}
            style={{ marginTop: 8 }}
            onClick={() => void refetch()}
          >
            Tentar novamente
          </button>
        </div>
      </div>
    )
  }

  if (evolutionResult.status === 'insufficient_data') {
    return (
      <div className={styles.evolutionContainer}>
        <div className={styles.header}>
          <div className={styles.titleArea}>
            <h3 className={styles.title}>
              <FontAwesomeIcon icon={faChartLine} style={{ color: '#60a5fa' }} />
              Evolução Temporal da Equipe
            </h3>
            <span className={styles.subtitle}>
              Série histórica de colaboração e topologia da rede
            </span>
          </div>
          <div className={styles.toggleGroup}>
            <button
              type="button"
              className={`${styles.toggleBtn} ${granularity === 'sprint' ? styles.toggleBtnActive : ''}`}
              onClick={() => setGranularity('sprint')}
            >
              Por Sprint
            </button>
            <button
              type="button"
              className={`${styles.toggleBtn} ${granularity === '14d' ? styles.toggleBtnActive : ''}`}
              onClick={() => setGranularity('14d')}
            >
              A cada 14 dias
            </button>
          </div>
        </div>
        <div className={styles.stateBox}>
          <FontAwesomeIcon
            icon={faTriangleExclamation}
            style={{ color: '#f59e0b', fontSize: '1.5rem', marginBottom: 8 }}
          />
          <p>{evolutionResult.reason ?? 'Menos de 2 períodos com dados suficientes.'}</p>
          <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
            Cadastre ao menos 2 sprints ou selecione o período de 14 dias para visualizar a evolução.
          </span>
        </div>
      </div>
    )
  }

  const periods = evolutionResult.values.periods ?? []
  if (periods.length < 2) {
    return null
  }

  // Cálculos de coordenadas SVG
  const width = 680
  const height = 220
  const padLeft = 55
  const padRight = 30
  const padTop = 30
  const padBottom = 40

  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom

  const values = periods.map((p) => Number(p[selectedMetric.key]) || 0)
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const range = rawMax - rawMin || 1
  const minVal = Math.max(0, rawMin - range * 0.1)
  const maxVal = rawMax + range * 0.15

  const points = periods.map((period, idx) => {
    const val = Number(period[selectedMetric.key]) || 0
    const x = padLeft + (idx / (periods.length - 1)) * plotWidth
    const y = padTop + plotHeight - ((val - minVal) / (maxVal - minVal || 1)) * plotHeight
    return { x, y, val, period, idx }
  })

  // Montar path de linha e área
  const linePathD = points.reduce((acc, pt, i) => {
    return i === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`
  }, '')

  const areaPathD = `${linePathD} L ${points[points.length - 1].x} ${padTop + plotHeight} L ${points[0].x} ${padTop + plotHeight} Z`

  // Checar se há alerta COLLAB_DROP no último delta
  const lastDelta = evolutionResult.values.delta
  const hasCollabDrop = Boolean(
    lastDelta && lastDelta.density_drop_pct >= 0.3,
  )

  const activeHover = hoveredIndex !== null ? points[hoveredIndex] : null

  return (
    <div className={styles.evolutionContainer}>
      <div className={styles.header}>
        <div className={styles.titleArea}>
          <h3 className={styles.title}>
            <FontAwesomeIcon icon={faChartLine} style={{ color: '#60a5fa' }} />
            Evolução Temporal da Equipe
          </h3>
          <span className={styles.subtitle}>
            Variação da topologia e colaboração ao longo de {periods.length} períodos ({granularity === 'sprint' ? 'Sprints' : 'Janelas de 14 dias'})
          </span>
        </div>

        <div className={styles.controls}>
          <div className={styles.toggleGroup}>
            <button
              type="button"
              className={`${styles.toggleBtn} ${granularity === 'sprint' ? styles.toggleBtnActive : ''}`}
              onClick={() => {
                setGranularity('sprint')
                setHoveredIndex(null)
              }}
            >
              Por Sprint
            </button>
            <button
              type="button"
              className={`${styles.toggleBtn} ${granularity === '14d' ? styles.toggleBtnActive : ''}`}
              onClick={() => {
                setGranularity('14d')
                setHoveredIndex(null)
              }}
            >
              A cada 14 dias
            </button>
          </div>

          <select
            className={styles.metricSelect}
            value={selectedMetricKey}
            onChange={(e) => {
              setSelectedMetricKey(e.target.value as MetricOption['key'])
              setHoveredIndex(null)
            }}
            aria-label="Selecionar métrica para o gráfico"
          >
            {METRIC_OPTIONS.map((opt) => (
              <option key={opt.key} value={opt.key}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {hasCollabDrop && (
        <div className={styles.collabDropBadge}>
          <FontAwesomeIcon icon={faTriangleExclamation} />
          <span>
            Queda brusca de colaboração detectada no último período:{' '}
            <strong>-{(lastDelta!.density_drop_pct * 100).toFixed(0)}%</strong> em intensidade
          </span>
        </div>
      )}

      <div className={styles.chartWrapper}>
        <svg
          className={styles.svgChart}
          viewBox={`0 0 ${width} ${height}`}
          aria-label={`Gráfico de evolução: ${selectedMetric.label}`}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Linhas de Grade Horizontal (4 níveis) */}
          {[0, 0.33, 0.66, 1].map((pct, idx) => {
            const y = padTop + plotHeight * pct
            const val = maxVal - pct * (maxVal - minVal)
            return (
              <g key={idx}>
                <line
                  x1={padLeft}
                  y1={y}
                  x2={width - padRight}
                  y2={y}
                  className={styles.gridLine}
                />
                <text x={padLeft - 8} y={y + 3} textAnchor="end" className={styles.axisText}>
                  {selectedMetric.format(val)}
                </text>
              </g>
            )
          })}

          {/* Área sombreada */}
          <path d={areaPathD} fill={`url(#${gradientId})`} />

          {/* Linha da métrica */}
          <path
            d={linePathD}
            fill="none"
            stroke="#60a5fa"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Linhas verticais e labels do eixo X */}
          {points.map((pt) => {
            const isHovered = hoveredIndex === pt.idx
            return (
              <g
                key={pt.idx}
                className={styles.pointGroup}
                onMouseEnter={() => setHoveredIndex(pt.idx)}
                onMouseLeave={() => setHoveredIndex(null)}
                onClick={() => {
                  if (onSelectPeriod) {
                    const param =
                      granularity === 'sprint'
                        ? `sprint:${pt.period.label.toLowerCase().replace(/\s+/g, '-')}`
                        : `${pt.period.from}:${pt.period.to}`
                    onSelectPeriod(param)
                  }
                }}
              >
                {/* Linha vertical de guia sob hover */}
                {isHovered && (
                  <line
                    x1={pt.x}
                    y1={padTop}
                    x2={pt.x}
                    y2={padTop + plotHeight}
                    stroke="rgba(96, 165, 250, 0.4)"
                    strokeWidth="1.5"
                    strokeDasharray="3 3"
                  />
                )}

                {/* Ponto */}
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r={isHovered ? 6 : 4.5}
                  fill={isHovered ? '#ffffff' : '#3b82f6'}
                  stroke="#1e3a8a"
                  strokeWidth="2"
                  className={styles.mainPoint}
                />

                {/* Indicador de queda de colaboração */}
                {pt.period.delta && pt.period.delta.density_drop_pct >= 0.3 && (
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r={8.5}
                    fill="none"
                    stroke="#ef4444"
                    strokeWidth="1.8"
                    strokeDasharray="2 2"
                  />
                )}

                {/* Label X */}
                <text
                  x={pt.x}
                  y={height - 12}
                  textAnchor="middle"
                  className={styles.axisText}
                  style={{
                    fill: isHovered ? '#f8fafc' : '#94a3b8',
                    fontWeight: isHovered ? 700 : 500,
                  }}
                >
                  {pt.period.label}
                </text>
              </g>
            )
          })}
        </svg>

        {/* Tooltip flutuante interativo */}
        {activeHover && (
          <div className={styles.tooltipContainer}>
            <div className={styles.tooltipLabel}>{activeHover.period.label}</div>
            <div className={styles.tooltipDates}>
              {activeHover.period.from} até {activeHover.period.to}
            </div>
            <div className={styles.tooltipValue}>
              {selectedMetric.format(activeHover.val)}
            </div>

            {activeHover.period.delta && (
              <div
                className={`${styles.tooltipDelta} ${
                  activeHover.period.delta.density_drop_pct >= 0.3
                    ? styles.deltaNegative
                    : styles.deltaPositive
                }`}
              >
                <FontAwesomeIcon
                  icon={
                    activeHover.period.delta.density_drop_pct >= 0.3
                      ? faArrowTrendDown
                      : faArrowTrendUp
                  }
                />
                <span>
                  {activeHover.period.delta.density_drop_pct >= 0.3
                    ? `Queda de ${(activeHover.period.delta.density_drop_pct * 100).toFixed(0)}% vs anterior`
                    : `Variação de densidade: ${(activeHover.period.delta.delta_density * 100).toFixed(1)}%`}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tabela resumida de comparação dos períodos */}
      <div className={styles.summaryTableWrapper}>
        <table className={styles.summaryTable}>
          <thead>
            <tr>
              <th>Período</th>
              <th>Datas</th>
              <th>Pessoas</th>
              <th>Intensidade</th>
              <th>Densidade</th>
              <th>Modularidade</th>
              <th>Reviews/PR</th>
              {onSelectPeriod && <th>Ação</th>}
            </tr>
          </thead>
          <tbody>
            {periods.map((p, idx) => (
              <tr key={idx}>
                <td style={{ fontWeight: 600, color: '#f8fafc' }}>
                  <FontAwesomeIcon
                    icon={faCircle}
                    style={{
                      fontSize: 8,
                      marginRight: 6,
                      color:
                        p.delta && p.delta.density_drop_pct >= 0.3
                          ? '#ef4444'
                          : '#3b82f6',
                    }}
                  />
                  {p.label}
                </td>
                <td style={{ color: '#94a3b8' }}>
                  {p.from} a {p.to}
                </td>
                <td>{p.active_people_count}</td>
                <td>
                  <strong>{p.weight_per_person.toFixed(2)}</strong>
                  {p.delta && p.delta.density_drop_pct >= 0.3 && (
                    <span style={{ color: '#ef4444', marginLeft: 6, fontSize: '0.75rem' }}>
                      (-{(p.delta.density_drop_pct * 100).toFixed(0)}%)
                    </span>
                  )}
                </td>
                <td>{(p.density * 100).toFixed(1)}%</td>
                <td>{p.modularity.toFixed(3)}</td>
                <td>{p.reviews_per_pr.toFixed(2)}</td>
                {onSelectPeriod && (
                  <td>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      onClick={() => {
                        const param =
                          granularity === 'sprint'
                            ? `sprint:${p.label.toLowerCase().replace(/\s+/g, '-')}`
                            : `${p.from}:${p.to}`
                        onSelectPeriod(param)
                      }}
                      title={`Ver ${p.label} no grafo`}
                    >
                      <FontAwesomeIcon icon={faEye} style={{ marginRight: 4 }} />
                      Ver no Grafo
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
