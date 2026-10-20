import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark, faPenToSquare, faTrash, faPlus } from '@fortawesome/free-solid-svg-icons'
import { api, type Sprint } from '../../api/client'
import styles from './SprintModal.module.css'

type SprintModalProps = {
  projectId: string
  isOpen: boolean
  onClose: () => void
  onSelectSprint?: (sprintId: string) => void
}

export const SprintModal = ({
  projectId,
  isOpen,
  onClose,
  onSelectSprint,
}: SprintModalProps) => {
  const queryClient = useQueryClient()
  const [editingSprintId, setEditingSprintId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const sprintsQuery = useQuery({
    queryKey: ['projectSprints', projectId],
    queryFn: () => api.get<Sprint[]>(`/projects/${projectId}/sprints`),
    enabled: isOpen && Boolean(projectId),
  })

  const createMutation = useMutation({
    mutationFn: (data: { name: string; start_date: string; end_date: string }) =>
      api.post<Sprint>(`/projects/${projectId}/sprints`, data),
    onSuccess: async (created) => {
      resetForm()
      await queryClient.invalidateQueries({ queryKey: ['projectSprints', projectId] })
      if (onSelectSprint) onSelectSprint(created.id)
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || 'Erro ao criar sprint.')
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: { sprintId: string; name: string; start_date: string; end_date: string }) =>
      api.put<Sprint>(`/projects/${projectId}/sprints/${data.sprintId}`, {
        name: data.name,
        start_date: data.start_date,
        end_date: data.end_date,
      }),
    onSuccess: async () => {
      resetForm()
      await queryClient.invalidateQueries({ queryKey: ['projectSprints', projectId] })
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || 'Erro ao atualizar sprint.')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (sprintId: string) =>
      api.delete(`/projects/${projectId}/sprints/${sprintId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['projectSprints', projectId] })
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || 'Erro ao excluir sprint.')
    },
  })

  const resetForm = () => {
    setEditingSprintId(null)
    setName('')
    setStartDate('')
    setEndDate('')
    setErrorMessage(null)
  }

  const handleStartEdit = (sprint: Sprint) => {
    setEditingSprintId(sprint.id)
    setName(sprint.name)
    setStartDate(sprint.start_civil || '')
    setEndDate(sprint.end_civil || '')
    setErrorMessage(null)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)

    if (!name.trim()) {
      setErrorMessage('Informe o nome da sprint.')
      return
    }
    if (!startDate || !endDate) {
      setErrorMessage('Informe as datas de início e término.')
      return
    }
    if (startDate > endDate) {
      setErrorMessage('A data inicial não pode ser posterior à final.')
      return
    }

    if (editingSprintId) {
      updateMutation.mutate({
        sprintId: editingSprintId,
        name: name.trim(),
        start_date: startDate,
        end_date: endDate,
      })
    } else {
      createMutation.mutate({
        name: name.trim(),
        start_date: startDate,
        end_date: endDate,
      })
    }
  }

  if (!isOpen) return null

  const sprints = sprintsQuery.data ?? []

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal="true">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleArea}>
            <h2>Gerenciar Sprints</h2>
            <p>Defina os períodos de sprint para análise do grafo e métricas do projeto</p>
          </div>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Fechar modal de sprints"
          >
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        <div className={styles.body}>
          {errorMessage && (
            <div className={styles.errorBanner} role="alert">
              {errorMessage}
            </div>
          )}

          <form className={styles.formCard} onSubmit={handleSubmit}>
            <span className={styles.formTitle}>
              {editingSprintId ? 'Editar Sprint' : 'Cadastrar Nova Sprint'}
            </span>
            <div className={styles.formGrid}>
              <div className={styles.field}>
                <label htmlFor="sprint-name">Nome da Sprint</label>
                <input
                  id="sprint-name"
                  type="text"
                  className={styles.input}
                  placeholder="Ex: Sprint 1"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="sprint-start">Data de Início</label>
                <input
                  id="sprint-start"
                  type="date"
                  className={styles.input}
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="sprint-end">Data de Fim</label>
                <input
                  id="sprint-end"
                  type="date"
                  className={styles.input}
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="submit"
                  className={styles.submitBtn}
                  disabled={createMutation.isPending || updateMutation.isPending}
                >
                  <FontAwesomeIcon icon={editingSprintId ? faPenToSquare : faPlus} style={{ marginRight: 6 }} />
                  {editingSprintId ? 'Atualizar' : 'Adicionar'}
                </button>
                {editingSprintId && (
                  <button
                    type="button"
                    className={styles.cancelEditBtn}
                    onClick={resetForm}
                  >
                    Cancelar
                  </button>
                )}
              </div>
            </div>
          </form>

          <div className={styles.sprintList}>
            <span className={styles.formTitle}>Sprints do Projeto ({sprints.length})</span>
            {sprintsQuery.isLoading ? (
              <p className={styles.emptyMsg}>Carregando sprints...</p>
            ) : sprints.length === 0 ? (
              <p className={styles.emptyMsg}>Nenhuma sprint cadastrada no projeto.</p>
            ) : (
              sprints.map((sprint) => (
                <div key={sprint.id} className={styles.sprintItem}>
                  <div className={styles.sprintInfo}>
                    <span className={styles.sprintName}>{sprint.name}</span>
                    <span className={styles.sprintDates}>
                      {sprint.start_civil || '—'} até {sprint.end_civil || '—'}
                    </span>
                  </div>

                  <div className={styles.sprintActions}>
                    {onSelectSprint && (
                      <button
                        type="button"
                        className={styles.actionIconBtn}
                        onClick={() => {
                          onSelectSprint(sprint.id)
                          onClose()
                        }}
                        title="Filtrar grafo por esta sprint"
                      >
                        Visualizar
                      </button>
                    )}
                    <button
                      type="button"
                      className={styles.actionIconBtn}
                      onClick={() => handleStartEdit(sprint)}
                      title="Editar sprint"
                    >
                      <FontAwesomeIcon icon={faPenToSquare} />
                    </button>
                    <button
                      type="button"
                      className={`${styles.actionIconBtn} ${styles.deleteBtn}`}
                      onClick={() => {
                        if (confirm(`Deseja excluir a sprint "${sprint.name}"?`)) {
                          deleteMutation.mutate(sprint.id)
                        }
                      }}
                      title="Excluir sprint"
                    >
                      <FontAwesomeIcon icon={faTrash} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
