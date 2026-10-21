import { useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark, faLightbulb, faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import type { GraphSelection } from './types'
import type { MetricCatalogEntry, MetricResult, Signal } from '../../api/client'
import SignalsPanel from '../Insights/SignalsPanel'
import AnalysisPanel from '../Insights/AnalysisPanel'
import styles from './rightDock.module.css'

const nodeTypeLabels: Record<string, string> = {
  person: 'Pessoa',
  task: 'Issue',
  pr: 'Pull request',
  commit: 'Commit',
  repo: 'Repositório',
  module: 'Módulo',
  column: 'Coluna',
}

type RightDockProps = {
  isOpen: boolean
  onClose: () => void
  activeTab: 'details' | 'insights'
  onTabChange: (tab: 'details' | 'insights') => void
  selection: GraphSelection
  metrics?: Record<string, MetricResult>
  catalog?: MetricCatalogEntry[]
  signals?: Signal[]
  signalsLoading?: boolean
  signalsError?: boolean
  onRetrySignals?: () => void
  selectedSignalId?: string | null
  onSignalClick?: (signal: Signal) => void
  projectId?: string
  windowVal?: string
}

const RightDock = ({
  isOpen,
  onClose,
  activeTab,
  onTabChange,
  selection,
  metrics,
  catalog,
  signals = [],
  signalsLoading = false,
  signalsError = false,
  onRetrySignals,
  selectedSignalId,
  onSignalClick,
  projectId = '',
  windowVal = '30d',
}: RightDockProps) => {
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null)
  const [insightsSubTab, setInsightsSubTab] = useState<'signals' | 'analysis'>('signals')

  if (!isOpen) return null

  const handleGenerateAi = () => {
    setInsightsSubTab('analysis')
  }

  // Contagem dinâmica de signals com severidade alta
  const highSignalsCount = signals.filter((s) => s.severity === 'high').length

  return (
    <aside className={styles.dock} aria-label="Painel de detalhes e insights">
      <div className={styles.dockHeader}>
        <div className={styles.tabs} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'details'}
            className={`${styles.tabBtn} ${activeTab === 'details' ? styles.activeTab : ''}`}
            onClick={() => onTabChange('details')}
          >
            <FontAwesomeIcon icon={faCircleInfo} />
            <span>Detalhes</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'insights'}
            className={`${styles.tabBtn} ${activeTab === 'insights' ? styles.activeTab : ''}`}
            onClick={() => onTabChange('insights')}
          >
            <FontAwesomeIcon icon={faLightbulb} />
            <span>Insights</span>
            {highSignalsCount > 0 && <span className={styles.badge}>{highSignalsCount}</span>}
          </button>
        </div>

        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Fechar painel direito"
          title="Fechar painel direito (])"
        >
          <FontAwesomeIcon icon={faXmark} />
        </button>
      </div>

      <div className={styles.dockBody}>
        {activeTab === 'details' ? (
          <>
            {!selection ? (
              <p className={styles.emptyPrompt}>
                Clique em um nó ou aresta para ver detalhes.
              </p>
            ) : selection.kind === 'node' ? (
              <>
                <h2 className={styles.nodeTitle}>{selection.data.label}</h2>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <span className={styles.nodeTypeBadge}>
                    {nodeTypeLabels[selection.data.type] ?? selection.data.type}
                  </span>
                  {selection.data.status_category && (
                    <span className={styles.flagBadge}>
                      {selection.data.status_category}
                    </span>
                  )}
                  {selection.data.flags?.map((flag) => (
                    <span className={styles.flagBadge} key={flag}>
                      {flag === 'bot' ? 'Bot' : flag}
                    </span>
                  ))}
                </div>

                {/* Métricas do Nó */}
                {(() => {
                  const nodeId = selection.data.id
                  const catalogMap = new Map(catalog?.map((c) => [c.id, c]))
                  const relevantIds = [
                    'person.overall',
                    'person.participation',
                    'person.collaboration',
                    'person.delivery',
                    'person.quality',
                    'graph.degree',
                    'graph.pagerank',
                    'graph.betweenness',
                    'flow.wip_per_person',
                  ]

                  const rows: Array<{ id: string; name: string; valStr: string }> = []
                  relevantIds.forEach((mId) => {
                    const mResult = metrics?.[mId]
                    if (mResult && mResult.values && typeof mResult.values === 'object') {
                      const v = mResult.values[nodeId]
                      if (v !== undefined && v !== null) {
                        const numVal = typeof v === 'object' && 'overall' in v ? v.overall : v
                        if (typeof numVal === 'number') {
                          const cat = catalogMap.get(mId)
                          rows.push({
                            id: mId,
                            name: cat?.name ?? mId,
                            valStr: numVal.toFixed(2),
                          })
                        }
                      }
                    }
                  })

                  // Fallback para métricas embutidas no próprio nó
                  if (rows.length === 0 && selection.data.metrics) {
                    Object.entries(selection.data.metrics).forEach(([k, v]) => {
                      if (typeof v === 'number' && Number.isFinite(v)) {
                        rows.push({ id: k, name: k, valStr: v.toFixed(2) })
                      }
                    })
                  }

                  if (rows.length === 0) return null

                  return (
                    <div style={{ marginTop: 12 }}>
                      <strong style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                        Métricas Calculadas
                      </strong>
                      {rows.map(({ id, name, valStr }) => {
                        const cat = catalogMap.get(id)
                        return (
                          <div className={styles.detailRow} key={id} style={{ position: 'relative' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span>{name}</span>
                              {cat && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setActiveTooltip(activeTooltip === id ? null : id)
                                  }
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    color: '#64748b',
                                    cursor: 'pointer',
                                    padding: 0,
                                  }}
                                  aria-label={`Ver fórmula de ${name}`}
                                >
                                  <FontAwesomeIcon icon={faCircleInfo} style={{ fontSize: 11 }} />
                                </button>
                              )}
                            </div>
                            <span style={{ fontWeight: 600, color: '#c084fc' }}>{valStr}</span>

                            {activeTooltip === id && cat && (
                              <div
                                style={{
                                  position: 'absolute',
                                  top: '100%',
                                  left: 0,
                                  right: 0,
                                  background: '#0f0b29',
                                  border: '1px solid #8b5cf6',
                                  padding: 8,
                                  borderRadius: 6,
                                  fontSize: 11,
                                  zIndex: 50,
                                  boxShadow: '0 8px 20px rgba(0,0,0,0.6)',
                                }}
                              >
                                <p style={{ margin: 0, color: '#e2e8f0' }}>{cat.description}</p>
                                <span
                                  style={{
                                    color: '#c084fc',
                                    fontFamily: 'monospace',
                                    display: 'block',
                                    marginTop: 4,
                                  }}
                                >
                                  Fórmula: {cat.formula}
                                </span>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}

                {selection.data.url && (
                  <a
                    href={selection.data.url}
                    target="_blank"
                    rel="noreferrer"
                    className={styles.externalLink}
                  >
                    Abrir no GitHub →
                  </a>
                )}
              </>
            ) : (
              /* Aresta selecionada */
              <>
                <h2 className={styles.nodeTitle}>Relação</h2>
                <span className={styles.nodeTypeBadge}>
                  {String(selection.data.type ?? 'Aresta')}
                </span>

                <div className={styles.detailRow}>
                  <span>Origem</span>
                  <span>{String(selection.data.source ?? '-')}</span>
                </div>
                <div className={styles.detailRow}>
                  <span>Destino</span>
                  <span>{String(selection.data.target ?? '-')}</span>
                </div>
                <div className={styles.detailRow}>
                  <span>Peso</span>
                  <span>{String(selection.data.weight ?? 1)}</span>
                </div>

                {selection.data.breakdown && typeof selection.data.breakdown === 'object' && (
                  <div style={{ marginTop: 8 }}>
                    <strong style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                      Detalhamento (Breakdown)
                    </strong>
                    {Object.entries(selection.data.breakdown as Record<string, unknown>).map(
                      ([k, v]) => (
                        <div className={styles.detailRow} key={k}>
                          <span>{k}</span>
                          <span>{String(v)}</span>
                        </div>
                      ),
                    )}
                  </div>
                )}
              </>
            )}
          </>
        ) : insightsSubTab === 'analysis' ? (
          /* Aba Insights: Análise com IA (SPEC §9.8, §12.4.1) */
          <AnalysisPanel
            projectId={projectId}
            windowVal={windowVal}
            selectedPersonUid={
              selection?.kind === 'node' && selection.data.type === 'person'
                ? selection.data.id
                : null
            }
            onBackToSignals={() => setInsightsSubTab('signals')}
          />
        ) : (
          /* Aba Insights: Signals determinísticos e riscos (SPEC §8, §12.5) */
          <SignalsPanel
            signals={signals}
            isLoading={signalsLoading}
            isError={signalsError}
            onRetry={onRetrySignals}
            selectedSignalId={selectedSignalId}
            onSignalClick={onSignalClick}
            onGenerateAi={handleGenerateAi}
          />
        )}
      </div>
    </aside>
  )
}

export default RightDock
