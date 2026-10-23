import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faCodeCompare,
  faArrowRightArrowLeft,
  faXmark,
  faCheck,
  faEye,
} from '@fortawesome/free-solid-svg-icons'
import { evolutionApi, type TeamEvolutionResult } from '../../api/client'
import styles from './periodCompareBar.module.css'

type PeriodCompareBarProps = {
  projectId: string
  currentWindow: string
  onWindowChange: (w: string) => void
  onClose: () => void
}

export const PeriodCompareBar = ({
  projectId,
  currentWindow,
  onWindowChange,
  onClose,
}: PeriodCompareBarProps) => {
  const { data: evolutionResult } = useQuery<TeamEvolutionResult>({
    queryKey: ['teamEvolution', projectId, 'sprint'],
    queryFn: () => evolutionApi.getEvolution(projectId, 'sprint'),
    enabled: Boolean(projectId),
  })

  const periods = evolutionResult?.values.periods ?? []

  // Inicializar Período A e B com os dois últimos períodos (ou os 2 primeiros)
  const [userAIndex, setUserAIndex] = useState<number | null>(null)
  const [userBIndex, setUserBIndex] = useState<number | null>(null)

  const defaultAIndex = Math.max(0, periods.length - 2)
  const defaultBIndex = Math.max(0, periods.length - 1)

  const periodAIndex = userAIndex !== null && userAIndex < periods.length ? userAIndex : defaultAIndex
  const periodBIndex = userBIndex !== null && userBIndex < periods.length ? userBIndex : defaultBIndex

  const setPeriodAIndex = (idx: number) => setUserAIndex(idx)
  const setPeriodBIndex = (idx: number) => setUserBIndex(idx)

  const periodA = periods[periodAIndex]
  const periodB = periods[periodBIndex]

  const getWindowParam = (label: string) =>
    `sprint:${label.toLowerCase().replace(/\s+/g, '-')}`

  const windowParamA = periodA ? getWindowParam(periodA.label) : ''
  const windowParamB = periodB ? getWindowParam(periodB.label) : ''

  const isCurrentA = currentWindow === windowParamA
  const isCurrentB = currentWindow === windowParamB

  const handleToggleSwap = () => {
    if (isCurrentA) {
      if (windowParamB) onWindowChange(windowParamB)
    } else {
      if (windowParamA) onWindowChange(windowParamA)
    }
  }

  if (periods.length < 2) {
    return (
      <div className={styles.compareContainer}>
        <div className={styles.topRow}>
          <div className={styles.titleSection}>
            <FontAwesomeIcon icon={faCodeCompare} className={styles.titleIcon} />
            <span>Comparar Períodos</span>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fechar">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>
        <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>
          São necessárias ao menos 2 sprints para comparar períodos lado a lado.
        </p>
      </div>
    )
  }

  return (
    <div className={styles.compareContainer} role="region" aria-label="Comparador de períodos">
      <div className={styles.topRow}>
        <div className={styles.titleSection}>
          <FontAwesomeIcon icon={faCodeCompare} className={styles.titleIcon} />
          <span>Comparar Períodos (Transição Animada)</span>
        </div>

        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Fechar comparador"
          title="Fechar comparador"
        >
          <FontAwesomeIcon icon={faXmark} />
        </button>
      </div>

      <div className={styles.selectionRow}>
        {/* Período A */}
        <div className={`${styles.periodCard} ${isCurrentA ? styles.periodCardActive : ''}`}>
          <span className={styles.periodLabel}>Período A:</span>
          <select
            className={styles.periodSelect}
            value={periodAIndex}
            onChange={(e) => setPeriodAIndex(Number(e.target.value))}
            aria-label="Selecionar Período A"
          >
            {periods.map((p, idx) => (
              <option key={idx} value={idx}>
                {p.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`${styles.viewBtn} ${isCurrentA ? styles.viewBtnCurrent : ''}`}
            onClick={() => windowParamA && onWindowChange(windowParamA)}
            title={isCurrentA ? 'Ativo no grafo' : `Exibir ${periodA?.label} no grafo com animação`}
          >
            <FontAwesomeIcon icon={isCurrentA ? faCheck : faEye} />
            <span>{isCurrentA ? 'Ativo' : 'Ver'}</span>
          </button>
        </div>

        {/* Botão de Alternância com animação */}
        <button
          type="button"
          className={styles.swapBtn}
          onClick={handleToggleSwap}
          title="Alternar entre Período A e B (anima o grafo)"
        >
          <FontAwesomeIcon icon={faArrowRightArrowLeft} />
          <span>Alternar (A ↔ B)</span>
        </button>

        {/* Período B */}
        <div className={`${styles.periodCard} ${isCurrentB ? styles.periodCardActive : ''}`}>
          <span className={styles.periodLabel}>Período B:</span>
          <select
            className={styles.periodSelect}
            value={periodBIndex}
            onChange={(e) => setPeriodBIndex(Number(e.target.value))}
            aria-label="Selecionar Período B"
          >
            {periods.map((p, idx) => (
              <option key={idx} value={idx}>
                {p.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`${styles.viewBtn} ${isCurrentB ? styles.viewBtnCurrent : ''}`}
            onClick={() => windowParamB && onWindowChange(windowParamB)}
            title={isCurrentB ? 'Ativo no grafo' : `Exibir ${periodB?.label} no grafo com animação`}
          >
            <FontAwesomeIcon icon={isCurrentB ? faCheck : faEye} />
            <span>{isCurrentB ? 'Ativo' : 'Ver'}</span>
          </button>
        </div>
      </div>

      {/* Mini resumo de métricas comparadas */}
      {periodA && periodB && (
        <div className={styles.metricsComparison}>
          <div className={styles.metricItem}>
            <span className={styles.metricTitle}>Pessoas Ativas:</span>
            <span className={styles.metricValue}>
              {periodA.active_people_count} → {periodB.active_people_count}
            </span>
          </div>

          <div className={styles.metricItem}>
            <span className={styles.metricTitle}>Densidade:</span>
            <span className={styles.metricValue}>
              {(periodA.density * 100).toFixed(0)}% → {(periodB.density * 100).toFixed(0)}%
            </span>
            {periodB.density >= periodA.density ? (
              <span className={styles.badgeDeltaUp}>+</span>
            ) : (
              <span className={styles.badgeDeltaDown}>-</span>
            )}
          </div>

          <div className={styles.metricItem}>
            <span className={styles.metricTitle}>Intensidade Média:</span>
            <span className={styles.metricValue}>
              {periodA.weight_per_person.toFixed(1)} → {periodB.weight_per_person.toFixed(1)}
            </span>
            {periodB.weight_per_person < periodA.weight_per_person && (
              <span
                className={styles.badgeDeltaDown}
                title="Queda de intensidade entre os períodos"
              >
                (
                {(
                  ((periodB.weight_per_person - periodA.weight_per_person) /
                    (periodA.weight_per_person || 1)) *
                  100
                ).toFixed(0)}
                %)
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
