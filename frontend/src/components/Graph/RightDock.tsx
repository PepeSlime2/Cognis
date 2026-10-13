import { useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark, faLightbulb, faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import type { GraphSelection } from './types'
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
}

const RightDock = ({
  isOpen,
  onClose,
  activeTab,
  onTabChange,
  selection,
}: RightDockProps) => {
  const [aiGenerating, setAiGenerating] = useState(false)
  const [aiMessage, setAiMessage] = useState<string | null>(null)

  if (!isOpen) return null

  const handleGenerateAi = () => {
    setAiGenerating(true)
    setTimeout(() => {
      setAiGenerating(false)
      setAiMessage('Análise concluída: Grafo balanceado com forte colaboração em pull requests.')
    }, 1500)
  }

  // Contagem de signals high
  const highSignalsCount = 1

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

                {selection.data.metrics && (
                  <div style={{ marginTop: 8 }}>
                    <strong style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                      Métricas
                    </strong>
                    {Object.entries(selection.data.metrics)
                      .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
                      .map(([k, v]) => (
                        <div className={styles.detailRow} key={k}>
                          <span>{k}</span>
                          <span>{Number(v).toFixed(2)}</span>
                        </div>
                      ))}
                  </div>
                )}

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
        ) : (
          /* Aba Insights */
          <div className={styles.insightsContainer}>
            <button
              type="button"
              className={styles.generateAiBtn}
              onClick={handleGenerateAi}
              disabled={aiGenerating}
            >
              <FontAwesomeIcon icon={faLightbulb} />
              <span>{aiGenerating ? 'Gerando Análise com IA…' : 'Gerar Análise com IA'}</span>
            </button>

            {aiMessage && (
              <div className={styles.insightCard} role="status">
                <span className={styles.insightTitle}>Diagnóstico LLM</span>
                <p className={styles.insightDesc}>{aiMessage}</p>
              </div>
            )}

            <div className={`${styles.insightCard} ${styles.insightCardHigh}`}>
              <div className={styles.insightHeader}>
                <span className={styles.insightTitle}>Concentração de Revisões</span>
                <span className={styles.badge}>Alta</span>
              </div>
              <p className={styles.insightDesc}>
                Poucos membros estão concentrando mais de 60% das aprovações de Pull Requests.
              </p>
            </div>

            <div className={styles.insightCard}>
              <div className={styles.insightHeader}>
                <span className={styles.insightTitle}>Módulos Desconectados</span>
              </div>
              <p className={styles.insightDesc}>
                Nenhum módulo isolado detectado na janela atual.
              </p>
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}

export default RightDock
