import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faShieldHalved,
  faSliders,
  faCodeBranch,
  faRotateRight,
  faEye,
  faXmark,
  faArrowLeft,
  faWandMagicSparkles,
  faUserSecret,
  faCheck,
  faFileLines,
} from '@fortawesome/free-solid-svg-icons'
import {
  api,
  type Analysis,
  type AnalysisScope,
  type AnalysisCreateRequest,
} from '../../api/client'
import styles from './analysisPanel.module.css'

export type AnalysisPanelProps = {
  projectId: string
  windowVal?: string
  selectedPersonUid?: string | null
  onBackToSignals?: () => void
}

/**
 * Destaca números no texto com marcação visual elegante.
 * Garante que números citados na análise de IA/regras fiquem destacados e verificáveis (F7.5).
 */
function renderHighlightedText(text: string) {
  if (!text) return null
  const numberRegex = /(\b\d+(?:[.,]\d+)?%?\b)/g
  const parts = text.split(numberRegex)

  return (
    <>
      {parts.map((part, index) => {
        if (/^\d+(?:[.,]\d+)?%?$/.test(part)) {
          return (
            <mark
              key={index}
              className={styles.verifiedNumber}
              title="Número verificado contra fatos determinísticos"
            >
              {part}
            </mark>
          )
        }
        return <span key={index}>{part}</span>
      })}
    </>
  )
}

export const AnalysisPanel = ({
  projectId,
  windowVal = '30d',
  selectedPersonUid,
  onBackToSignals,
}: AnalysisPanelProps) => {
  const queryClient = useQueryClient()

  // Estados locais de configuração da análise
  const [scope, setScope] = useState<AnalysisScope>('team')
  const [anonymize, setAnonymize] = useState(false)
  const [activeAnalysisId, setActiveAnalysisId] = useState<string | null>(null)
  const [showFactsModal, setShowFactsModal] = useState(false)
  const [copiedFacts, setCopiedFacts] = useState(false)

  // 1. Listar análises recentes do projeto
  const listQuery = useQuery({
    queryKey: ['projectAnalyses', projectId],
    queryFn: () => api.get<Analysis[]>(`/projects/${projectId}/analyses`),
    enabled: Boolean(projectId),
  })

  // Identificar a análise ativa: ou a explicitamente selecionada ou a mais recente
  const currentAnalysisId = useMemo(() => {
    if (activeAnalysisId) return activeAnalysisId
    if (listQuery.data && listQuery.data.length > 0) {
      return listQuery.data[0].id
    }
    return null
  }, [activeAnalysisId, listQuery.data])

  // 2. Consulta da análise ativa com polling automático enquanto estiver em andamento
  const currentAnalysisQuery = useQuery({
    queryKey: ['analysis', currentAnalysisId],
    queryFn: () => api.get<Analysis>(`/analyses/${currentAnalysisId}`),
    enabled: Boolean(currentAnalysisId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'pending' || status === 'running') {
        return 2000 // Polling a cada 2s enquanto o job estiver rodando
      }
      return false
    },
  })

  // 3. Mutação para disparar uma nova análise
  const createMutation = useMutation({
    mutationFn: (req: AnalysisCreateRequest) =>
      api.post<Analysis>(`/projects/${projectId}/analyses`, req),
    onSuccess: (data) => {
      const newId = data.id || data.analysis_id
      setActiveAnalysisId(newId)
      void queryClient.invalidateQueries({ queryKey: ['projectAnalyses', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['analysis', newId] })
    },
  })

  const handleStartAnalysis = (forceTemplate = false) => {
    const payload: AnalysisCreateRequest = {
      scope,
      anonymize,
      force_template: forceTemplate,
    }

    if (windowVal.startsWith('sprint:')) {
      payload.sprint_id = windowVal.replace('sprint:', '')
    } else {
      payload.window = windowVal
    }

    if (scope === 'person' && selectedPersonUid) {
      payload.person_uid = selectedPersonUid
    }

    createMutation.mutate(payload)
  }

  const analysis = currentAnalysisQuery.data
  const isJobRunning =
    createMutation.isPending ||
    analysis?.status === 'pending' ||
    analysis?.status === 'running'

  const handleCopyFacts = async () => {
    if (!analysis?.facts) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(analysis.facts, null, 2))
      setCopiedFacts(true)
      setTimeout(() => setCopiedFacts(false), 2000)
    } catch {
      // Ignora erro de clipboard se bloqueado pelo browser
    }
  }

  return (
    <div className={styles.container} aria-label="Painel de Análise de IA">
      {/* Barra Superior de Navegação */}
      <div className={styles.topBar}>
        {onBackToSignals && (
          <button
            type="button"
            className={styles.backBtn}
            onClick={onBackToSignals}
            aria-label="Voltar para lista de signals"
          >
            <FontAwesomeIcon icon={faArrowLeft} />
            <span>Signals</span>
          </button>
        )}

        <div className={styles.titleArea}>
          <FontAwesomeIcon icon={faWandMagicSparkles} />
          <span>Análise Cognis</span>
        </div>

        {listQuery.data && listQuery.data.length > 1 && (
          <select
            className={styles.selectInput}
            value={currentAnalysisId ?? ''}
            onChange={(e) => setActiveAnalysisId(e.target.value)}
            aria-label="Selecionar análise do histórico"
          >
            {listQuery.data.map((an) => (
              <option key={an.id} value={an.id}>
                {an.scope} · {an.source === 'ollama' ? 'IA' : 'Regras'} (
                {an.created_at ? new Date(an.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : an.id.slice(0, 6)})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Caixa de Configurações para Gerar Nova Análise */}
      <div className={styles.configBox}>
        <div className={styles.configRow}>
          <label className={styles.configLabel} htmlFor="analysis-scope-select">
            <FontAwesomeIcon icon={faSliders} />
            <span>Escopo:</span>
          </label>
          <select
            id="analysis-scope-select"
            className={styles.selectInput}
            value={scope}
            onChange={(e) => setScope(e.target.value as AnalysisScope)}
            disabled={isJobRunning}
          >
            <option value="team">Equipe & Dinâmica Geral</option>
            <option value="collaboration">Colaboração & Silos</option>
            <option value="risks">Riscos & Gargalos</option>
            <option value="sprint">Fluxo da Sprint</option>
            {selectedPersonUid && <option value="person">Pessoa Selecionada</option>}
          </select>
        </div>

        <div className={styles.configRow}>
          <label className={styles.checkboxLabel} title="Substitui nomes reais por Pessoa A, Pessoa B nos dados enviados ao modelo">
            <input
              type="checkbox"
              className={styles.checkboxInput}
              checked={anonymize}
              onChange={(e) => setAnonymize(e.target.checked)}
              disabled={isJobRunning}
            />
            <FontAwesomeIcon icon={faUserSecret} />
            <span>Anonimizar dados (SPEC §9.4)</span>
          </label>

          <button
            type="button"
            className={styles.actionButton}
            onClick={() => handleStartAnalysis(false)}
            disabled={isJobRunning}
            aria-label="Gerar análise com inteligência artificial"
          >
            <FontAwesomeIcon
              icon={isJobRunning ? faRotateRight : faWandMagicSparkles}
              className={isJobRunning ? styles.spinningIcon : ''}
            />
            <span>{isJobRunning ? 'Analisando…' : 'Gerar Análise'}</span>
          </button>
        </div>
      </div>

      {/* Estado: Job em Andamento (Polling) */}
      {isJobRunning && (
        <div className={styles.progressCard} role="status" aria-live="polite">
          <div className={styles.progressHeader}>
            <FontAwesomeIcon icon={faRotateRight} className={styles.spinningIcon} />
            <span>
              {analysis?.status === 'running'
                ? 'Consultando IA local (llama3.1:8b) e validando números…'
                : 'Preparando métricas e estruturando fatos da janela…'}
            </span>
          </div>

          <div className={styles.progressBarContainer}>
            <div className={styles.progressBarIndeterminate} />
          </div>

          <span className={styles.progressText}>
            O modelo local Llama 3.1 8B opera com lock exclusivo e verificação anti-alucinação.
            Isso pode levar alguns segundos.
          </span>
        </div>
      )}

      {/* Estado: Falha na Análise */}
      {analysis?.status === 'failed' && !isJobRunning && (
        <div className={styles.errorState} role="alert">
          <strong>Não foi possível concluir a análise</strong>
          <span>
            {analysis.validation?.error ??
              'O modelo local pode estar temporariamente indisponível ou ocupado.'}
          </span>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => handleStartAnalysis(true)}
            style={{ alignSelf: 'flex-start', marginTop: 4 }}
          >
            <FontAwesomeIcon icon={faFileLines} />
            <span>Gerar via regras (Template)</span>
          </button>
        </div>
      )}

      {/* Estado: Análise Concluída */}
      {analysis?.status === 'completed' && analysis.result && !isJobRunning && (
        <>
          {/* Selos Obrigatórios de Conformidade (SPEC §9.8) */}
          {analysis.source === 'ollama' ? (
            <div className={styles.badgeOllama} role="status">
              <FontAwesomeIcon icon={faShieldHalved} />
              <span>
                Gerado por IA local (llama3.1:8b) · números verificados automaticamente · revise antes de decidir
              </span>
            </div>
          ) : analysis.source === 'template' ? (
            <div className={styles.badgeTemplate} role="status">
              <FontAwesomeIcon icon={faFileLines} />
              <span>
                Texto gerado por regras (IA indisponível ou reprovada na verificação)
              </span>
            </div>
          ) : (
            <div className={styles.badgeMixed} role="status">
              <FontAwesomeIcon icon={faCodeBranch} />
              <span>
                Texto híbrido (partes geradas por IA local e partes geradas por regras)
              </span>
            </div>
          )}

          {/* Resumo Executivo */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>Resumo da Dinâmica</span>
            </div>
            <p className={styles.resumoText}>
              {renderHighlightedText(analysis.result.resumo)}
            </p>
          </div>

          {/* Achados (Findings) */}
          {analysis.result.achados && analysis.result.achados.length > 0 && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>
                  Achados Principais ({analysis.result.achados.length})
                </span>
              </div>
              <div className={styles.findingsList}>
                {analysis.result.achados.map((item, idx) => (
                  <div key={idx} className={styles.findingCard}>
                    <div className={styles.findingTop}>
                      <span className={styles.findingTitle}>{item.titulo}</span>
                      <span
                        className={
                          item.severidade === 'alta'
                            ? styles.sevBadgeAlta
                            : item.severidade === 'media'
                              ? styles.sevBadgeMedia
                              : styles.sevBadgeBaixa
                        }
                      >
                        {item.severidade}
                      </span>
                    </div>

                    <p className={styles.findingDesc}>
                      {renderHighlightedText(item.descricao)}
                    </p>

                    {item.evidencias && item.evidencias.length > 0 && (
                      <div className={styles.evidenceRow}>
                        {item.evidencias.map((ev, evIdx) => (
                          <span key={evIdx} className={styles.evidenceTag} title={`Referência: ${ev.ref}`}>
                            {ev.ref}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recomendações Práticas */}
          {analysis.result.recomendacoes && analysis.result.recomendacoes.length > 0 && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>
                  Ações Recomendadas ({analysis.result.recomendacoes.length})
                </span>
              </div>
              <div className={styles.recList}>
                {analysis.result.recomendacoes.map((rec, idx) => (
                  <div key={idx} className={styles.recCard}>
                    <span className={styles.recAction}>{rec.acao}</span>
                    <p className={styles.recJust}>
                      {renderHighlightedText(rec.justificativa)}
                    </p>
                    {rec.evidencias && rec.evidencias.length > 0 && (
                      <div className={styles.evidenceRow}>
                        {rec.evidencias.map((ev, evIdx) => (
                          <span key={evIdx} className={styles.evidenceTag} title={`Evidência: ${ev.ref}`}>
                            {ev.ref}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Limitações e Notas de Amostra */}
          {analysis.result.limitacoes && analysis.result.limitacoes.length > 0 && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Limitações & Amostra</span>
              </div>
              <ul className={styles.limitationsList}>
                {analysis.result.limitacoes.map((lim, idx) => (
                  <li key={idx}>{lim}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Ações do Rodapé: Ver dados usados (SPEC §9.8) */}
          <div className={styles.footerActions}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => setShowFactsModal(true)}
              aria-label="Ver dados usados na análise"
            >
              <FontAwesomeIcon icon={faEye} />
              <span>Ver dados usados</span>
            </button>

            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => handleStartAnalysis(false)}
              aria-label="Atualizar análise"
            >
              <FontAwesomeIcon icon={faRotateRight} />
              <span>Reanalisar</span>
            </button>
          </div>
        </>
      )}

      {/* Estado Vazio (Sem análises ainda) */}
      {!analysis && !isJobRunning && !listQuery.isLoading && (
        <div className={styles.emptyState}>
          <FontAwesomeIcon icon={faWandMagicSparkles} style={{ fontSize: 24, color: '#8b5cf6' }} />
          <h4 className={styles.emptyStateTitle}>Nenhuma análise gerada</h4>
          <p className={styles.emptyStateText}>
            Clique no botão acima para sintetizar métricas, identificar padrões de colaboração e
            receber recomendações acionáveis geradas por IA local.
          </p>
        </div>
      )}

      {/* Modal de Transparência: Ver Dados Usados (facts_json) */}
      {showFactsModal && analysis?.facts && (
        <div
          className={styles.modalOverlay}
          onClick={() => setShowFactsModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-facts-title"
        >
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 id="modal-facts-title">
                <FontAwesomeIcon icon={faEye} style={{ color: '#8b5cf6' }} />
                <span>Dados Usados na Análise (FATOS)</span>
              </h3>
              <button
                type="button"
                className={styles.closeModalBtn}
                onClick={() => setShowFactsModal(false)}
                aria-label="Fechar modal"
              >
                <FontAwesomeIcon icon={faXmark} />
              </button>
            </div>

            <pre className={styles.modalBody}>
              {JSON.stringify(analysis.facts, null, 2)}
            </pre>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={handleCopyFacts}
              >
                <FontAwesomeIcon icon={copiedFacts ? faCheck : faFileLines} />
                <span>{copiedFacts ? 'Copiado!' : 'Copiar JSON'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AnalysisPanel
