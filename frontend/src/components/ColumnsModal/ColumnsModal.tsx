import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faTriangleExclamation, faTableColumns, faXmark } from '@fortawesome/free-solid-svg-icons'
import { api, type ColumnCategory, type ColumnMappingsResponse } from '../../api/client'
import styles from './ColumnsModal.module.css'

type ColumnsModalProps = {
  projectId: string
  isOpen: boolean
  onClose: () => void
}

const CATEGORY_LABELS: Record<ColumnCategory, string> = {
  backlog: 'Backlog',
  todo: 'A Fazer (Todo)',
  doing: 'Em Andamento (Doing)',
  review: 'Revisão / QA (Review)',
  done: 'Concluído (Done)',
}

export const ColumnsModal = ({ projectId, isOpen, onClose }: ColumnsModalProps) => {
  const queryClient = useQueryClient()
  const [userOverrides, setUserOverrides] = useState<Record<string, ColumnCategory>>({})
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const columnsQuery = useQuery({
    queryKey: ['projectColumns', projectId],
    queryFn: () => api.get<ColumnMappingsResponse>(`/projects/${projectId}/columns`),
    enabled: isOpen && Boolean(projectId),
  })

  const saveMutation = useMutation({
    mutationFn: (updates: Array<{ column_uid: string; category: ColumnCategory }>) =>
      api.put<ColumnMappingsResponse>(`/projects/${projectId}/columns`, { columns: updates }),
    onSuccess: async () => {
      setFeedback({ type: 'success', message: 'Mapeamento de colunas atualizado com sucesso!' })
      await queryClient.invalidateQueries({ queryKey: ['projectColumns', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['projectGraph', projectId] })
      setTimeout(() => {
        setFeedback(null)
        onClose()
      }, 1200)
    },
    onError: (err: Error) => {
      setFeedback({
        type: 'error',
        message: err.message || 'Não foi possível salvar o mapeamento de colunas.',
      })
    },
  })

  if (!isOpen) return null

  const handleCategoryChange = (columnUid: string, category: ColumnCategory) => {
    setUserOverrides((prev) => ({
      ...prev,
      [columnUid]: category,
    }))
  }

  const handleSave = () => {
    if (!columnsQuery.data?.columns) return
    const updates = columnsQuery.data.columns.map((col) => ({
      column_uid: col.column_uid,
      category: userOverrides[col.column_uid] ?? col.category,
    }))
    saveMutation.mutate(updates)
  }

  const columns = columnsQuery.data?.columns ?? []
  const hasUnconfirmed = columnsQuery.data?.warnings.includes('columns_unconfirmed')

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="columns-modal-title">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleArea}>
            <h2 id="columns-modal-title">
              <FontAwesomeIcon icon={faTableColumns} style={{ color: '#a78bfa' }} />
              Mapeamento de Colunas (Trello)
            </h2>
            <p className={styles.subtitle}>
              Classifique as listas do Trello para cálculo determinístico de fluxo e lead time.
            </p>
          </div>
          <button className={styles.closeBtn} onClick={onClose} type="button" aria-label="Fechar modal">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        <div className={styles.body}>
          {hasUnconfirmed && (
            <div className={styles.warningBanner} role="alert">
              <FontAwesomeIcon icon={faTriangleExclamation} />
              <span>
                Há colunas com mapeamento automático pendente de confirmação. Confirme para habilitar métricas de fluxo sem alertas.
              </span>
            </div>
          )}

          {columnsQuery.isPending ? (
            <div className={styles.stateCard}>
              <p>Carregando colunas do projeto...</p>
            </div>
          ) : columnsQuery.isError ? (
            <div className={styles.stateCard} role="alert">
              <h3>Não foi possível carregar as colunas</h3>
              <p>{columnsQuery.error instanceof Error ? columnsQuery.error.message : 'Erro inesperado.'}</p>
              <button
                className={styles.cancelBtn}
                style={{ marginTop: 8 }}
                onClick={() => void columnsQuery.refetch()}
                type="button"
              >
                Tentar novamente
              </button>
            </div>
          ) : columns.length === 0 ? (
            <div className={styles.stateCard}>
              <h3>Nenhuma coluna encontrada</h3>
              <p>Conecte um board do Trello ao projeto e execute uma sincronização para listar as colunas.</p>
            </div>
          ) : (
            <div className={styles.columnsList}>
              {columns.map((col) => {
                const currentCategory = userOverrides[col.column_uid] ?? col.category
                const isAuto = col.source === 'auto'

                return (
                  <div key={col.column_uid} className={styles.columnRow}>
                    <div className={styles.columnInfo}>
                      <span className={styles.columnName} title={col.name}>
                        {col.name}
                      </span>
                      <div className={styles.badgeRow}>
                        <span className={isAuto ? styles.badgeAuto : styles.badgeUser}>
                          {isAuto ? 'Classificação Automática' : 'Confirmado pelo Usuário'}
                        </span>
                      </div>
                    </div>

                    <select
                      className={styles.selectCategory}
                      value={currentCategory}
                      onChange={(e) => handleCategoryChange(col.column_uid, e.target.value as ColumnCategory)}
                      aria-label={`Categoria para ${col.name}`}
                    >
                      {(Object.keys(CATEGORY_LABELS) as ColumnCategory[]).map((cat) => (
                        <option key={cat} value={cat}>
                          {CATEGORY_LABELS[cat]}
                        </option>
                      ))}
                    </select>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className={styles.footer}>
          {feedback?.type === 'success' && (
            <span className={styles.feedbackSuccess} role="status">
              {feedback.message}
            </span>
          )}
          {feedback?.type === 'error' && (
            <span className={styles.feedbackError} role="alert">
              {feedback.message}
            </span>
          )}
          <button className={styles.cancelBtn} onClick={onClose} type="button">
            Cancelar
          </button>
          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={saveMutation.isPending || columns.length === 0}
            type="button"
          >
            {saveMutation.isPending ? 'Salvando...' : 'Confirmar Mapeamento'}
          </button>
        </div>
      </div>
    </div>
  )
}
