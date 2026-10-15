import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faCodeMerge,
  faEye,
  faEyeSlash,
  faLinkSlash,
  faPen,
  faUsers,
  faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { api, type PeopleResponse, type Person, type PersonAccount } from '../../api/client'
import modal from '../ColumnsModal/ColumnsModal.module.css'
import styles from './identity.module.css'

type PeopleModalProps = {
  projectId: string
  isOpen: boolean
  onClose: () => void
}

const PROVIDER_LABELS: Record<string, string> = {
  github: 'GitHub',
  trello: 'Trello',
  git: 'Git',
}

const personName = (person: Person | undefined) =>
  person?.display_name || person?.accounts[0]?.login || 'Colaborador'

const accountLabel = (acc: PersonAccount | null) =>
  acc ? `${PROVIDER_LABELS[acc.provider ?? ''] ?? acc.provider ?? '—'}: ${acc.login ?? acc.display_name ?? '—'}` : '—'

export const PeopleModal = ({ projectId, isOpen, onClose }: PeopleModalProps) => {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [keepUid, setKeepUid] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ uid: string; name: string } | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const peopleQuery = useQuery({
    queryKey: ['projectPeople', projectId],
    queryFn: () => api.get<PeopleResponse>(`/projects/${projectId}/people`),
    enabled: isOpen && Boolean(projectId),
  })

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['projectPeople', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] }),
    ])
  }

  const onError = (err: Error) =>
    setFeedback({ type: 'error', message: err.message || 'Não foi possível concluir a operação.' })

  const mergeMutation = useMutation({
    mutationFn: (payload: { keep_person_id: string; merge_person_ids: string[] }) =>
      api.post(`/projects/${projectId}/people/merge`, payload),
    onSuccess: async () => {
      setSelected([])
      setKeepUid(null)
      setFeedback({ type: 'success', message: 'Pessoas mescladas. O grafo foi atualizado.' })
      await refreshAll()
    },
    onError,
  })

  const splitMutation = useMutation({
    mutationFn: (payload: { personUid: string; accountUid: string }) =>
      api.post(`/projects/${projectId}/people/${encodeURIComponent(payload.personUid)}/split`, {
        account_uid: payload.accountUid,
      }),
    onSuccess: async () => {
      setFeedback({ type: 'success', message: 'Conta separada em uma nova pessoa.' })
      await refreshAll()
    },
    onError,
  })

  const patchMutation = useMutation({
    mutationFn: (payload: { personUid: string; display_name?: string; excluded?: boolean }) => {
      const { personUid, ...body } = payload
      return api.patch(`/projects/${projectId}/people/${encodeURIComponent(personUid)}`, body)
    },
    onSuccess: async () => {
      setEditing(null)
      setFeedback({ type: 'success', message: 'Pessoa atualizada.' })
      await refreshAll()
    },
    onError,
  })

  if (!isOpen) return null

  const busy = mergeMutation.isPending || splitMutation.isPending || patchMutation.isPending
  const people = peopleQuery.data?.people ?? []
  const suggestions = peopleQuery.data?.suggestions ?? []
  const peopleByUid = new Map(people.map((p) => [p.person_uid, p]))
  const visiblePeople = showExcluded ? people : people.filter((p) => !p.excluded)
  const excludedCount = people.length - people.filter((p) => !p.excluded).length

  const toggleSelected = (uid: string) => {
    setSelected((prev) => (prev.includes(uid) ? prev.filter((u) => u !== uid) : [...prev, uid]))
  }

  const effectiveKeep = keepUid && selected.includes(keepUid) ? keepUid : selected[0]

  const handleMergeSelected = () => {
    if (selected.length < 2 || !effectiveKeep) return
    mergeMutation.mutate({
      keep_person_id: effectiveKeep,
      merge_person_ids: selected.filter((u) => u !== effectiveKeep),
    })
  }

  const saveRename = () => {
    if (!editing) return
    const name = editing.name.trim()
    if (!name) {
      setFeedback({ type: 'error', message: 'O nome não pode ficar vazio.' })
      return
    }
    patchMutation.mutate({ personUid: editing.uid, display_name: name })
  }

  return (
    <div className={modal.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="people-modal-title">
      <div className={`${modal.modal} ${styles.wide}`} onClick={(e) => e.stopPropagation()}>
        <div className={modal.header}>
          <div className={modal.titleArea}>
            <h2 id="people-modal-title">
              <FontAwesomeIcon icon={faUsers} style={{ color: '#a78bfa' }} />
              Pessoas do Projeto
            </h2>
            <p className={modal.subtitle}>
              Unifique contas do GitHub, Trello e Git da mesma pessoa, renomeie ou oculte colaboradores do grafo.
            </p>
          </div>
          <button className={modal.closeBtn} onClick={onClose} type="button" aria-label="Fechar modal">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        <div className={modal.body}>
          {peopleQuery.isPending ? (
            <div className={modal.stateCard}>
              <p>Carregando pessoas do projeto...</p>
            </div>
          ) : peopleQuery.isError ? (
            <div className={modal.stateCard} role="alert">
              <h3>Não foi possível carregar as pessoas</h3>
              <p>{peopleQuery.error instanceof Error ? peopleQuery.error.message : 'Erro inesperado.'}</p>
              <button className={modal.cancelBtn} style={{ marginTop: 8 }} onClick={() => void peopleQuery.refetch()} type="button">
                Tentar novamente
              </button>
            </div>
          ) : people.length === 0 ? (
            <div className={modal.stateCard}>
              <h3>Nenhuma pessoa encontrada</h3>
              <p>Execute uma sincronização para importar os colaboradores das fontes conectadas.</p>
            </div>
          ) : (
            <>
              {suggestions.length > 0 && (
                <section className={styles.block} aria-label="Sugestões de unificação">
                  <h3 className={styles.blockTitle}>Sugestões de unificação</h3>
                  {suggestions.map((s) => {
                    const a = peopleByUid.get(s.person_a_uid)
                    const b = peopleByUid.get(s.person_b_uid)
                    return (
                      <div key={`${s.person_a_uid}-${s.person_b_uid}`} className={styles.suggestionRow}>
                        <div className={styles.suggestionInfo}>
                          <span className={styles.rowTitle}>
                            {personName(a)} ⇄ {personName(b)}
                          </span>
                          <span className={styles.rowMeta}>
                            {accountLabel(s.account_a)} · {accountLabel(s.account_b)} — {s.reason}
                          </span>
                        </div>
                        <button
                          type="button"
                          className={modal.saveBtn}
                          disabled={busy}
                          onClick={() =>
                            mergeMutation.mutate({ keep_person_id: s.person_a_uid, merge_person_ids: [s.person_b_uid] })
                          }
                        >
                          <FontAwesomeIcon icon={faCodeMerge} /> Mesclar
                        </button>
                      </div>
                    )
                  })}
                </section>
              )}

              <section className={styles.block} aria-label="Lista de pessoas">
                <div className={styles.blockHeader}>
                  <h3 className={styles.blockTitle}>
                    {visiblePeople.length} {visiblePeople.length === 1 ? 'pessoa' : 'pessoas'}
                  </h3>
                  {excludedCount > 0 && (
                    <label className={styles.toggleLabel}>
                      <input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
                      Mostrar ocultas ({excludedCount})
                    </label>
                  )}
                </div>

                {visiblePeople.map((person) => {
                  const isSelected = selected.includes(person.person_uid)
                  const isEditing = editing?.uid === person.person_uid
                  return (
                    <div
                      key={person.person_uid}
                      className={`${styles.personRow} ${isSelected ? styles.personSelected : ''} ${person.excluded ? styles.personExcluded : ''}`}
                    >
                      <input
                        type="checkbox"
                        className={styles.checkbox}
                        checked={isSelected}
                        onChange={() => toggleSelected(person.person_uid)}
                        aria-label={`Selecionar ${personName(person)} para mesclar`}
                      />
                      <div className={styles.personInfo}>
                        {isEditing ? (
                          <div className={styles.renameRow}>
                            <input
                              className={styles.textInput}
                              value={editing.name}
                              maxLength={255}
                              autoFocus
                              onChange={(e) => setEditing({ uid: person.person_uid, name: e.target.value })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveRename()
                                if (e.key === 'Escape') setEditing(null)
                              }}
                              aria-label="Novo nome"
                            />
                            <button type="button" className={modal.saveBtn} disabled={busy} onClick={saveRename}>
                              Salvar
                            </button>
                            <button type="button" className={modal.cancelBtn} onClick={() => setEditing(null)}>
                              Cancelar
                            </button>
                          </div>
                        ) : (
                          <span className={styles.rowTitle}>
                            {personName(person)}
                            {person.is_me && <span className={styles.badgeMe}>Você</span>}
                            {person.excluded && <span className={styles.badgeMuted}>Oculta</span>}
                          </span>
                        )}
                        <div className={styles.accountList}>
                          {person.accounts.map((acc) => (
                            <span key={acc.uid} className={styles.accountChip} title={acc.display_name ?? undefined}>
                              {accountLabel(acc)}
                              {acc.is_bot && <span className={styles.botTag}>bot</span>}
                              {person.accounts.length > 1 && (
                                <button
                                  type="button"
                                  className={styles.chipBtn}
                                  disabled={busy}
                                  onClick={() => splitMutation.mutate({ personUid: person.person_uid, accountUid: acc.uid })}
                                  aria-label={`Separar conta ${acc.login ?? acc.uid}`}
                                  title="Separar esta conta em outra pessoa"
                                >
                                  <FontAwesomeIcon icon={faLinkSlash} />
                                </button>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                      {isSelected && selected.length > 1 && (
                        <label className={styles.keepLabel} title="Pessoa que permanece após a mesclagem">
                          <input
                            type="radio"
                            name="keep-person"
                            checked={effectiveKeep === person.person_uid}
                            onChange={() => setKeepUid(person.person_uid)}
                          />
                          Manter
                        </label>
                      )}
                      {!isEditing && (
                        <div className={styles.rowActions}>
                          <button
                            type="button"
                            className={styles.iconBtn}
                            onClick={() => setEditing({ uid: person.person_uid, name: personName(person) })}
                            aria-label={`Renomear ${personName(person)}`}
                            title="Renomear"
                          >
                            <FontAwesomeIcon icon={faPen} />
                          </button>
                          <button
                            type="button"
                            className={styles.iconBtn}
                            disabled={busy}
                            onClick={() => patchMutation.mutate({ personUid: person.person_uid, excluded: !person.excluded })}
                            aria-label={person.excluded ? `Mostrar ${personName(person)}` : `Ocultar ${personName(person)}`}
                            title={person.excluded ? 'Mostrar no grafo e nas métricas' : 'Ocultar do grafo e das métricas'}
                          >
                            <FontAwesomeIcon icon={person.excluded ? faEye : faEyeSlash} />
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
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
          <button
            className={modal.saveBtn}
            onClick={handleMergeSelected}
            disabled={busy || selected.length < 2}
            type="button"
          >
            {mergeMutation.isPending ? 'Mesclando...' : `Mesclar selecionadas (${selected.length})`}
          </button>
        </div>
      </div>
    </div>
  )
}
