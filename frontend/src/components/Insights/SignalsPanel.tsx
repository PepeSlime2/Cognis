import { useState, useMemo } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faTriangleExclamation,
  faCircleExclamation,
  faCircleInfo,
  faCheckCircle,
  faBullseye,
  faRotateRight,
  faLayerGroup,
  faLightbulb,
} from '@fortawesome/free-solid-svg-icons'
import type { Signal, SignalSeverity } from '../../api/client'
import styles from './signalsPanel.module.css'

export type SignalsPanelProps = {
  signals?: Signal[]
  isLoading?: boolean
  isError?: boolean
  onRetry?: () => void
  selectedSignalId?: string | null
  onSignalClick?: (signal: Signal) => void
  onGenerateAi?: () => void
  aiGenerating?: boolean
  aiMessage?: string | null
}

const severityOrder: Record<SignalSeverity, number> = {
  high: 0,
  medium: 1,
  info: 2,
}

const severityLabels: Record<SignalSeverity, string> = {
  high: 'Alta',
  medium: 'Média',
  info: 'Informativo',
}

export const SignalsPanel = ({
  signals = [],
  isLoading = false,
  isError = false,
  onRetry,
  selectedSignalId,
  onSignalClick,
  onGenerateAi,
  aiGenerating = false,
  aiMessage,
}: SignalsPanelProps) => {
  const [filterSeverity, setFilterSeverity] = useState<SignalSeverity | 'all'>('all')

  // Ordenar sinais por severidade: high -> medium -> info
  const sortedSignals = useMemo(() => {
    return [...signals].sort((a, b) => {
      const orderA = severityOrder[a.severity] ?? 99
      const orderB = severityOrder[b.severity] ?? 99
      if (orderA !== orderB) return orderA - orderB
      return a.code.localeCompare(b.code)
    })
  }, [signals])

  // Contagens por severidade
  const counts = useMemo(() => {
    const c = { all: signals.length, high: 0, medium: 0, info: 0 }
    signals.forEach((s) => {
      if (s.severity in c) {
        c[s.severity] += 1
      }
    })
    return c
  }, [signals])

  // Sinais filtrados
  const filteredSignals = useMemo(() => {
    if (filterSeverity === 'all') return sortedSignals
    return sortedSignals.filter((s) => s.severity === filterSeverity)
  }, [sortedSignals, filterSeverity])

  // Detectar se há avisos de dados insuficientes
  const hasInsufficientData = useMemo(() => {
    return signals.some((s) => s.code === 'INSUFFICIENT_DATA')
  }, [signals])

  return (
    <div className={styles.container} aria-label="Painel de Signals e Riscos">
      {/* Botão de Análise com IA */}
      <div className={styles.headerActions}>
        {onGenerateAi && (
          <button
            type="button"
            className={styles.generateAiBtn}
            onClick={onGenerateAi}
            disabled={aiGenerating}
            aria-label="Gerar análise com inteligência artificial"
          >
            <FontAwesomeIcon icon={faLightbulb} />
            <span>{aiGenerating ? 'Gerando Análise com IA…' : 'Gerar Análise com IA'}</span>
          </button>
        )}

        {aiMessage && (
          <div className={styles.aiMessageCard} role="status">
            <div className={styles.aiMessageHeader}>
              <FontAwesomeIcon icon={faLightbulb} />
              <span>Diagnóstico IA</span>
            </div>
            <p style={{ margin: 0 }}>{aiMessage}</p>
          </div>
        )}
      </div>

      {/* Barra de Filtro de Severidade */}
      {signals.length > 0 && (
        <div className={styles.filterBar} role="toolbar" aria-label="Filtro de severidade de signals">
          <button
            type="button"
            className={`${styles.filterChip} ${filterSeverity === 'all' ? styles.filterChipActive : ''}`}
            onClick={() => setFilterSeverity('all')}
          >
            <FontAwesomeIcon icon={faLayerGroup} style={{ fontSize: 10 }} />
            <span>Todos</span>
            <span className={styles.filterBadge}>{counts.all}</span>
          </button>

          {counts.high > 0 && (
            <button
              type="button"
              className={`${styles.filterChip} ${filterSeverity === 'high' ? styles.filterChipActive : ''}`}
              onClick={() => setFilterSeverity('high')}
            >
              <span>Alta</span>
              <span className={`${styles.filterBadge} ${styles.filterBadgeHigh}`}>{counts.high}</span>
            </button>
          )}

          {counts.medium > 0 && (
            <button
              type="button"
              className={`${styles.filterChip} ${filterSeverity === 'medium' ? styles.filterChipActive : ''}`}
              onClick={() => setFilterSeverity('medium')}
            >
              <span>Média</span>
              <span className={`${styles.filterBadge} ${styles.filterBadgeMedium}`}>{counts.medium}</span>
            </button>
          )}

          {counts.info > 0 && (
            <button
              type="button"
              className={`${styles.filterChip} ${filterSeverity === 'info' ? styles.filterChipActive : ''}`}
              onClick={() => setFilterSeverity('info')}
            >
              <span>Info</span>
              <span className={`${styles.filterBadge} ${styles.filterBadgeInfo}`}>{counts.info}</span>
            </button>
          )}
        </div>
      )}

      {/* Aviso de Dados Insuficientes */}
      {hasInsufficientData && (
        <div className={styles.insufficientDataBanner} role="note">
          <FontAwesomeIcon icon={faCircleInfo} className={styles.insufficientIcon} />
          <div>
            <strong style={{ display: 'block', marginBottom: 2 }}>Amostra Mínima de Dados</strong>
            <span>
              Algumas métricas (lead time, retrabalho, cobertura) exigem um volume mínimo de eventos
              (ex.: pelo menos 5 tarefas concluídas ou PRs mesclados) para assegurar significância estatística.
            </span>
          </div>
        </div>
      )}

      {/* Estados: Loading, Erro, Vazio e Lista */}
      {isLoading ? (
        <div className={styles.loadingContainer} aria-busy="true">
          <div className={styles.spinner} />
          <span>Calculando signals e avaliando riscos…</span>
        </div>
      ) : isError ? (
        <div className={styles.errorContainer} role="alert">
          <FontAwesomeIcon icon={faTriangleExclamation} className={styles.errorIcon} />
          <span>Não foi possível carregar os signals do período.</span>
          {onRetry && (
            <button type="button" className={styles.retryBtn} onClick={onRetry}>
              <FontAwesomeIcon icon={faRotateRight} />
              <span>Tentar novamente</span>
            </button>
          )}
        </div>
      ) : filteredSignals.length === 0 ? (
        <div className={styles.emptyContainer}>
          <FontAwesomeIcon icon={faCheckCircle} className={styles.emptyIcon} />
          <strong style={{ color: 'var(--text-primary, #ffffff)' }}>Nenhum sinal detectado</strong>
          <span>
            {filterSeverity !== 'all'
              ? `Não há sinais com severidade "${severityLabels[filterSeverity]}" na janela atual.`
              : 'Nenhum risco de fluxo, sobrecarga ou silo identificado na janela selecionada.'}
          </span>
        </div>
      ) : (
        <div className={styles.signalsList} role="list">
          {filteredSignals.map((signal) => {
            const isSelected = selectedSignalId === signal.id
            const sevClass =
              signal.severity === 'high'
                ? styles.severityHigh
                : signal.severity === 'medium'
                  ? styles.severityMedium
                  : styles.severityInfo

            const badgeClass =
              signal.severity === 'high'
                ? styles.badgeHigh
                : signal.severity === 'medium'
                  ? styles.badgeMedium
                  : styles.badgeInfo

            const icon =
              signal.severity === 'high'
                ? faTriangleExclamation
                : signal.severity === 'medium'
                  ? faCircleExclamation
                  : faCircleInfo

            return (
              <div
                key={signal.id}
                role="listitem"
                tabIndex={0}
                className={`${styles.signalCard} ${sevClass} ${isSelected ? styles.signalCardActive : ''}`}
                onClick={() => onSignalClick?.(signal)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSignalClick?.(signal)
                  }
                }}
                aria-pressed={isSelected}
                aria-label={`${signal.title} - Severidade ${severityLabels[signal.severity]}`}
              >
                <div className={styles.cardHeader}>
                  <h3 className={styles.cardTitle}>{signal.title}</h3>
                  <span className={`${styles.badge} ${badgeClass}`}>
                    <FontAwesomeIcon icon={icon} style={{ fontSize: 9 }} />
                    <span>{severityLabels[signal.severity]}</span>
                  </span>
                </div>

                <p className={styles.cardMessage}>{signal.message}</p>

                {signal.subject && (
                  <div className={styles.subjectRow}>
                    <FontAwesomeIcon icon={faBullseye} style={{ fontSize: 10 }} />
                    <span>Alvo:</span>
                    <span className={styles.subjectBadge}>
                      {signal.subject.label || signal.subject.id}
                    </span>
                  </div>
                )}

                {signal.evidence && signal.evidence.length > 0 && (
                  <div className={styles.evidenceRow}>
                    {signal.evidence.map((ev, idx) => (
                      <span key={idx} className={styles.evidenceChip} title={`Métrica: ${ev.metric_id}`}>
                        {ev.metric_id}: {String(ev.value)} {ev.unit ? `(${ev.unit})` : ''}
                      </span>
                    ))}
                  </div>
                )}

                <div className={styles.highlightHint}>
                  <span>
                    {isSelected ? '✓ Nós em destaque no grafo' : 'Clique para destacar no grafo'}
                  </span>
                  {isSelected && <span className={styles.activeIndicator}>Ativo</span>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default SignalsPanel
