import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowRight, faLink, faPlus, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { api, type LinksResponse } from '../../api/client'
import modal from '../ColumnsModal/ColumnsModal.module.css'
import styles from './identity.module.css'

type LinksModalProps = {
  projectId: string
  isOpen: boolean
  onClose: () => void
}

const VIA_LABELS: Record<string, string> = {
  attachment: 'Anexo',
  text: 'Menção no texto',
  manual: 'Manual',
}

const KIND_LABELS: Record<string, string> = {
  pull_request: 'PR',
  issue: 'Issue',
}

export const LinksModal = ({ projectId, isOpen, onClose }: LinksModalProps) => {
  const queryClient = useQueryClient()
  const [sourceUid, setSourceUid] = useState('')
  const [targetUid, setTargetUid] = useState('')
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const linksQuery = useQuery({
    queryKey: ['projectLinks', projectId],
    queryFn: () => api.get<LinksResponse>(`/projects/${projectId}/links`),
    enabled: isOpen && Boolean(projectId),
  })

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['projectLinks', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] }),
    ])
  }

  const onError = (err: Error) =>
    setFeedback({ type: 'error', message: err.message || 'Não foi possível concluir a operação.' })

  const createMutation = useMutation({
    mutationFn: (payload: { source_uid: string; target_uid: string }) =>
      api.post(`/projects/${projectId}/links`, payload),
    onSuccess: async () => {
      setSourceUid('')
      setTargetUid('')
      setFeedback({ type: 'success', message: 'Vínculo criado. O grafo foi atualizado.' })
      await refreshAll()
    },
    onError,
  })

  const deleteMutation = useMutation({
    mutationFn: (payload: { source_uid: string; target_uid: string }) => {
      const params = new URLSearchParams(payload)
      return api.delete(`/projects/${projectId}/links?${params.toString()}`)
    },
    onSuccess: async () => {
      setFeedback({ type: 'success', message: 'Vínculo removido.' })
      await refreshAll()
    },
    onError,
  })

  if (!isOpen) return null

  const busy = createMutation.isPending || deleteMutation.isPending
  const links = linksQuery.data?.links ?? []
  const unlinked = linksQuery.data?.unlinked_tasks ?? []
  const candidates = linksQuery.data?.candidates ?? []

  return (
    <div className={modal.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="links-modal-title">
      <div className={`${modal.modal} ${styles.wide}`} onClick={(e) => e.stopPropagation()}>
        <div className={modal.header}>
          <div className={modal.titleArea}>
            <h2 id="links-modal-title">
              <FontAwesomeIcon icon={faLink} style={{ color: '#a78bfa' }} />
              Vínculos Trello ↔ GitHub
            </h2>
            <p className={modal.subtitle}>
              Vínculos detectados automaticamente (anexos e menções) e criados manualmente entre cards e PRs/issues.
            </p>
          </div>
          <button className={modal.closeBtn} onClick={onClose} type="button" aria-label="Fechar modal">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        <div className={modal.body}>
          {linksQuery.isPending ? (
            <div className={modal.stateCard}>
              <p>Carregando vínculos do projeto...</p>
            </div>
          ) : linksQuery.isError ? (
            <div className={modal.stateCard} role="alert">
              <h3>Não foi possível carregar os vínculos</h3>
              <p>{linksQuery.error instanceof Error ? linksQuery.error.message : 'Erro inesperado.'}</p>
              <button className={modal.cancelBtn} style={{ marginTop: 8 }} onClick={() => void linksQuery.refetch()} type="button">
                Tentar novamente
              </button>
            </div>
          ) : (
            <>
              <section className={styles.block} aria-label="Novo vínculo manual">
                <h3 className={styles.blockTitle}>Novo vínculo manual</h3>
                {unlinked.length === 0 || candidates.length === 0 ? (
                  <p className={styles.rowMeta}>
                    {unlinked.length === 0
                      ? 'Todos os cards do Trello já possuem vínculo (ou nenhum card foi sincronizado).'
                      : 'Nenhuma PR ou issue do GitHub sincronizada para vincular.'}
                  </p>
                ) : (
                  <div className={styles.linkForm}>
                    <select
                      className={modal.selectCategory}
                      value={sourceUid}
                      onChange={(e) => setSourceUid(e.target.value)}
                      aria-label="Card do Trello"
                    >
                      <option value="">Card do Trello…</option>
                      {unlinked.map((t) => (
                        <option key={t.uid} value={t.uid}>
                          {t.title}
                        </option>
                      ))}
                    </select>
                    <FontAwesomeIcon icon={faArrowRight} className={styles.arrow} />
                    <select
                      className={modal.selectCategory}
                      value={targetUid}
                      onChange={(e) => setTargetUid(e.target.value)}
                      aria-label="PR ou issue do GitHub"
                    >
                      <option value="">PR / issue do GitHub…</option>
                      {candidates.map((c) => (
                        <option key={c.uid} value={c.uid}>
                          [{KIND_LABELS[c.kind] ?? c.kind}] {c.title}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className={modal.saveBtn}
                      disabled={busy || !sourceUid || !targetUid}
                      onClick={() => createMutation.mutate({ source_uid: sourceUid, target_uid: targetUid })}
                    >
                      <FontAwesomeIcon icon={faPlus} /> {createMutation.isPending ? 'Criando...' : 'Vincular'}
                    </button>
                  </div>
                )}
              </section>

              <section className={styles.block} aria-label="Vínculos existentes">
                <h3 className={styles.blockTitle}>
                  {links.length} {links.length === 1 ? 'vínculo' : 'vínculos'}
                </h3>
                {links.length === 0 ? (
                  <div className={modal.stateCard}>
                    <h3>Nenhum vínculo ainda</h3>
                    <p>Anexe a PR ao card no Trello, cite o link do card na PR ou crie um vínculo manual acima.</p>
                  </div>
                ) : (
                  links.map((link) => (
                    <div key={`${link.source_uid}-${link.target_uid}`} className={styles.suggestionRow}>
                      <div className={styles.suggestionInfo}>
                        <span className={styles.rowTitle}>
                          {link.source_url ? (
                            <a href={link.source_url} target="_blank" rel="noreferrer" className={styles.extLink}>
                              {link.source_title}
                            </a>
                          ) : (
                            link.source_title
                          )}
                          <FontAwesomeIcon icon={faArrowRight} className={styles.arrow} />
                          <span className={styles.badgeMuted}>{KIND_LABELS[link.target_kind] ?? link.target_kind}</span>
                          {link.target_url ? (
                            <a href={link.target_url} target="_blank" rel="noreferrer" className={styles.extLink}>
                              {link.target_title}
                            </a>
                          ) : (
                            link.target_title
                          )}
                        </span>
                        <span className={styles.rowMeta}>Origem: {VIA_LABELS[link.via] ?? link.via}</span>
                      </div>
                      <button
                        type="button"
                        className={styles.iconBtn}
                        disabled={busy}
                        onClick={() => deleteMutation.mutate({ source_uid: link.source_uid, target_uid: link.target_uid })}
                        aria-label={`Remover vínculo ${link.source_title}`}
                        title="Remover vínculo"
                      >
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    </div>
                  ))
                )}
              </section>
            </>
          )}
        </div>

        <div className={modal.footer}>
          {feedback?.type === 'success' && (
            <span className={modal.feedbackSuccess} role="status">
              {feedback.message}
            </span>
          )}
          {feedback?.type === 'error' && (
            <span className={modal.feedbackError} role="alert">
              {feedback.message}
            </span>
          )}
          <button className={modal.cancelBtn} onClick={onClose} type="button">
            Fechar
          </button>
        </div>
      </div>
    </div>
  )
}
