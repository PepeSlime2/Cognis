import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faXmark,
  faFileLines,
  faDownload,
  faClockRotateLeft,
  faPlus,
  faFileCode,
  faFileWord,
  faFilePdf,
} from '@fortawesome/free-solid-svg-icons'
import {
  api,
  reportsApi,
  type ReportType,
  type ReportFormat,
  type ReportItem,
} from '../../api/client'
import styles from './reportDialog.module.css'

interface ReportDialogProps {
  projectId: string
  isOpen: boolean
  onClose: () => void
  initialType?: ReportType
}

type PersonOption = {
  uid: string
  name: string
  excluded?: boolean
}

const REPORT_TYPE_CONFIG: Record<
  ReportType,
  { title: string; desc: string; icon: string }
> = {
  sprint: {
    title: 'Sprint',
    desc: 'KPIs de entrega, vazão, reviews e resumo executivo.',
    icon: '⚡',
  },
  gerencial: {
    title: 'Gerencial',
    desc: 'Visão holística da equipe, imagem do grafo e riscos.',
    icon: '📊',
  },
  individual: {
    title: 'Individual',
    desc: 'Perfil de colaboração de 1 membro com aviso ético §13.4.',
    icon: '👤',
  },
  gargalos: {
    title: 'Gargalos',
    desc: 'Diagnóstico de tempos de espera, sobrecarga e bus factor.',
    icon: '⚠️',
  },
  colaboracao: {
    title: 'Colaboração',
    desc: 'Rede de colaboração, comunidades Louvain e pontes.',
    icon: '🌐',
  },
}

export const ReportDialog = ({
  projectId,
  isOpen,
  onClose,
  initialType = 'sprint',
}: ReportDialogProps) => {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'create' | 'history'>('create')
  const [selectedType, setSelectedType] = useState<ReportType>(initialType)
  const [prevInitialType, setPrevInitialType] = useState<ReportType>(initialType)

  if (initialType !== prevInitialType) {
    setPrevInitialType(initialType)
    setSelectedType(initialType)
  }

  const [selectedFormats, setSelectedFormats] = useState<ReportFormat[]>([
    'html',
    'docx',
    'pdf',
  ])
  const [selectedPersonUid, setSelectedPersonUid] = useState<string>('')
  const [selectedWindow, setSelectedWindow] = useState<string>('30d')
  const [includeAi, setIncludeAi] = useState<boolean>(true)
  const [anonymize, setAnonymize] = useState<boolean>(false)

  const [activeReportId, setActiveReportId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Fechar com tecla Esc
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  // Busca lista de pessoas para o relatório individual
  const { data: peopleData } = useQuery<PersonOption[]>({
    queryKey: ['projectPeople', projectId],
    queryFn: async () => {
      const res = await api.get<{ people: PersonOption[] } | PersonOption[]>(
        `/projects/${projectId}/people`,
      )
      if (Array.isArray(res)) return res
      return res.people || []
    },
    enabled: isOpen && selectedType === 'individual',
  })

  const effectivePersonUid =
    selectedPersonUid ||
    peopleData?.find((p) => !p.excluded)?.uid ||
    peopleData?.[0]?.uid ||
    ''

  // Histórico de relatórios
  const { data: historyReports, isLoading: isHistoryLoading } = useQuery<ReportItem[]>({
    queryKey: ['projectReports', projectId],
    queryFn: () => reportsApi.listReports(projectId),
    enabled: isOpen,
    refetchInterval: (query) => {
      const hasRunning = query.state.data?.some(
        (r) => r.status === 'pending' || r.status === 'processing',
      )
      return hasRunning ? 2000 : false
    },
  })

  // Consulta de polling para o relatório recém-criado
  const { data: currentReport } = useQuery<ReportItem>({
    queryKey: ['reportItem', activeReportId],
    queryFn: () => reportsApi.getReport(activeReportId!),
    enabled: Boolean(activeReportId),
    refetchInterval: (query) => {
      const st = query.state.data?.status
      if (st === 'completed' || st === 'failed') return false
      return 2000
    },
  })

  // Mutação para disparar geração do relatório
  const createMutation = useMutation({
    mutationFn: (payload: {
      type: ReportType
      formats: ReportFormat[]
      person_uid?: string
      window: string
      include_ai: boolean
      anonymize: boolean
    }) => reportsApi.createReport(projectId, payload),
    onSuccess: (data) => {
      setActiveReportId(data.id)
      setErrorMessage(null)
      queryClient.invalidateQueries({ queryKey: ['projectReports', projectId] })
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || 'Falha ao solicitar geração do relatório.')
    },
  })

  const toggleFormat = (fmt: ReportFormat) => {
    setSelectedFormats((prev) => {
      if (prev.includes(fmt)) {
        if (prev.length === 1) return prev // manter pelo menos 1
        return prev.filter((f) => f !== fmt)
      }
      return [...prev, fmt]
    })
  }

  const handleGenerate = () => {
    if (selectedType === 'individual' && !effectivePersonUid) {
      setErrorMessage('Selecione um colaborador para o relatório individual.')
      return
    }
    setErrorMessage(null)
    setActiveReportId(null)

    createMutation.mutate({
      type: selectedType,
      formats: selectedFormats,
      person_uid: selectedType === 'individual' ? effectivePersonUid : undefined,
      window: selectedWindow,
      include_ai: includeAi,
      anonymize,
    })
  }

  if (!isOpen) return null

  const isGenerating =
    createMutation.isPending ||
    (currentReport &&
      (currentReport.status === 'pending' || currentReport.status === 'processing'))

  const isCompleted = currentReport?.status === 'completed'

  return (
    <div className={styles.backdrop} onClick={onClose} role="dialog" aria-modal="true">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Cabeçalho */}
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <FontAwesomeIcon icon={faFileLines} className={styles.headerIcon} />
            <span>Central de Relatórios COGNIS</span>
          </div>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Fechar janela"
          >
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        {/* Abas */}
        <div className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'create' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('create')}
          >
            <FontAwesomeIcon icon={faPlus} />
            <span>Novo Relatório</span>
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'history' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('history')}
          >
            <FontAwesomeIcon icon={faClockRotateLeft} />
            <span>Histórico ({historyReports?.length ?? 0})</span>
          </button>
        </div>

        {/* Corpo */}
        <div className={styles.body}>
          {errorMessage && <div className={styles.errorBanner}>{errorMessage}</div>}

          {activeTab === 'create' ? (
            <>
              {/* Seleção do Tipo */}
              <div className={styles.formGroup}>
                <div className={styles.sectionLabel}>Tipo de Relatório</div>
                <div className={styles.typeGrid}>
                  {(Object.keys(REPORT_TYPE_CONFIG) as ReportType[]).map((t) => {
                    const cfg = REPORT_TYPE_CONFIG[t]
                    const isSelected = selectedType === t
                    return (
                      <div
                        key={t}
                        className={`${styles.typeCard} ${isSelected ? styles.typeSelected : ''}`}
                        onClick={() => setSelectedType(t)}
                      >
                        <span style={{ fontSize: '20px' }}>{cfg.icon}</span>
                        <span className={styles.typeTitle}>{cfg.title}</span>
                        <span className={styles.typeDesc}>{cfg.desc}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Seletor de Colaborador para Individual */}
              {selectedType === 'individual' && (
                <div className={styles.formGroup}>
                  <label htmlFor="report-person-select" className={styles.sectionLabel}>
                    Colaborador Alvo
                  </label>
                  <select
                    id="report-person-select"
                    className={styles.selectInput}
                    value={effectivePersonUid}
                    onChange={(e) => setSelectedPersonUid(e.target.value)}
                  >
                    {peopleData && peopleData.length > 0 ? (
                      peopleData.map((p) => (
                        <option key={p.uid} value={p.uid}>
                          {p.name} {p.excluded ? '(Excluído)' : ''}
                        </option>
                      ))
                    ) : (
                      <option value="">Nenhum colaborador encontrado</option>
                    )}
                  </select>
                </div>
              )}

              {/* Janela Temporal */}
              <div className={styles.formGroup}>
                <label htmlFor="report-window-select" className={styles.sectionLabel}>
                  Janela Temporal
                </label>
                <select
                  id="report-window-select"
                  className={styles.selectInput}
                  value={selectedWindow}
                  onChange={(e) => setSelectedWindow(e.target.value)}
                >
                  <option value="7d">Últimos 7 dias</option>
                  <option value="14d">Últimos 14 dias (2 semanas)</option>
                  <option value="30d">Últimos 30 dias (padrão)</option>
                  <option value="90d">Últimos 90 dias (trimestre)</option>
                </select>
              </div>

              {/* Formatos de Saída */}
              <div className={styles.formGroup}>
                <div className={styles.sectionLabel}>Formatos de Exportação</div>
                <div className={styles.formatsRow}>
                  <div
                    className={`${styles.formatChip} ${
                      selectedFormats.includes('html') ? styles.formatActive : ''
                    }`}
                    onClick={() => toggleFormat('html')}
                  >
                    <FontAwesomeIcon icon={faFileCode} style={{ color: '#10b981' }} />
                    <span>HTML (Offline)</span>
                  </div>
                  <div
                    className={`${styles.formatChip} ${
                      selectedFormats.includes('docx') ? styles.formatActive : ''
                    }`}
                    onClick={() => toggleFormat('docx')}
                  >
                    <FontAwesomeIcon icon={faFileWord} style={{ color: '#3b82f6' }} />
                    <span>DOCX (Word)</span>
                  </div>
                  <div
                    className={`${styles.formatChip} ${
                      selectedFormats.includes('pdf') ? styles.formatActive : ''
                    }`}
                    onClick={() => toggleFormat('pdf')}
                  >
                    <FontAwesomeIcon icon={faFilePdf} style={{ color: '#ef4444' }} />
                    <span>PDF (ReportLab)</span>
                  </div>
                </div>
              </div>

              {/* Toggles de IA e Anonimização */}
              <div className={styles.toggleRow}>
                <label className={styles.toggleLabel}>
                  <span>Incluir análise e recomendações de IA</span>
                  <input
                    type="checkbox"
                    className={styles.checkboxInput}
                    checked={includeAi}
                    onChange={(e) => setIncludeAi(e.target.checked)}
                  />
                </label>
                <label className={styles.toggleLabel}>
                  <span>Anonimizar nomes e identificadores (LGPD / Privacidade)</span>
                  <input
                    type="checkbox"
                    className={styles.checkboxInput}
                    checked={anonymize}
                    onChange={(e) => setAnonymize(e.target.checked)}
                  />
                </label>
              </div>

              {/* Estado de Progresso */}
              {isGenerating && (
                <div className={styles.progressBox}>
                  <div className={styles.spinner} />
                  <div className={styles.progressText}>
                    Gerando relatório {selectedType.toUpperCase()} nos formatos selecionados...
                  </div>
                </div>
              )}

              {/* Resultado de Sucesso com Links de Download */}
              {isCompleted && currentReport && (
                <div className={styles.successBox}>
                  <div style={{ fontWeight: 700, color: '#10b981' }}>
                    ✓ Relatório gerado com sucesso!
                  </div>
                  <div className={styles.downloadButtonsRow}>
                    {currentReport.formats.map((fmt) => (
                      <a
                        key={fmt}
                        href={reportsApi.getDownloadUrl(currentReport.id, fmt)}
                        target="_blank"
                        rel="noreferrer"
                        className={`${styles.downloadBtn} ${
                          fmt === 'docx'
                            ? styles.downloadBtnDocx
                            : fmt === 'pdf'
                            ? styles.downloadBtnPdf
                            : ''
                        }`}
                      >
                        <FontAwesomeIcon icon={faDownload} />
                        <span>Baixar {fmt.toUpperCase()}</span>
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            /* Aba Histórico */
            <div className={styles.historyList}>
              {isHistoryLoading ? (
                <div className={styles.emptyState}>Carregando histórico...</div>
              ) : historyReports && historyReports.length > 0 ? (
                historyReports.map((item) => (
                  <div key={item.id} className={styles.historyItem}>
                    <div className={styles.historyItemInfo}>
                      <span className={styles.historyItemTitle}>
                        Relatório {item.type}
                      </span>
                      <span className={styles.historyItemMeta}>
                        {item.created_at ? new Date(item.created_at).toLocaleString('pt-BR') : '—'} •{' '}
                        {item.status === 'completed'
                          ? 'Concluído'
                          : item.status === 'processing'
                          ? 'Processando'
                          : item.status}
                      </span>
                    </div>

                    <div className={styles.historyItemActions}>
                      {item.status === 'completed' && item.formats && item.formats.length > 0 ? (
                        item.formats.map((fmt) => (
                          <a
                            key={fmt}
                            href={reportsApi.getDownloadUrl(item.id, fmt)}
                            target="_blank"
                            rel="noreferrer"
                            className={`${styles.downloadBtn} ${
                              fmt === 'docx'
                                ? styles.downloadBtnDocx
                                : fmt === 'pdf'
                                ? styles.downloadBtnPdf
                                : ''
                            }`}
                            style={{ padding: '6px 10px', fontSize: '12px' }}
                          >
                            <FontAwesomeIcon icon={faDownload} />
                            <span>{fmt.toUpperCase()}</span>
                          </a>
                        ))
                      ) : (
                        <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                          {item.status}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className={styles.emptyState}>
                  Nenhum relatório foi gerado para este projeto ainda.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Rodapé de Ações */}
        <div className={styles.footer}>
          <button type="button" className={styles.cancelBtn} onClick={onClose}>
            Fechar
          </button>
          {activeTab === 'create' && (
            <button
              type="button"
              className={styles.submitBtn}
              onClick={handleGenerate}
              disabled={isGenerating}
            >
              {isGenerating ? 'Gerando...' : 'Gerar Relatório'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
