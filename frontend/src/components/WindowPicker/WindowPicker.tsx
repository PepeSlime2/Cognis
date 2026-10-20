import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCalendarDays, faPlus } from '@fortawesome/free-solid-svg-icons'
import { api, type Sprint } from '../../api/client'
import { SprintModal } from '../SprintModal/SprintModal'
import styles from './WindowPicker.module.css'

const standardWindows = [
  { id: '7d', label: '7d' },
  { id: '14d', label: '14d' },
  { id: '30d', label: '30d' },
  { id: '90d', label: '90d' },
]

type WindowPickerProps = {
  projectId: string
  windowVal: string
  onWindowChange: (w: string) => void
  showManageButton?: boolean
}

export const WindowPicker = ({
  projectId,
  windowVal,
  onWindowChange,
  showManageButton = true,
}: WindowPickerProps) => {
  const [modalOpen, setModalOpen] = useState(false)

  const sprintsQuery = useQuery({
    queryKey: ['projectSprints', projectId],
    queryFn: () => api.get<Sprint[]>(`/projects/${projectId}/sprints`),
    enabled: Boolean(projectId),
  })

  const sprints = sprintsQuery.data ?? []
  const isSprintSelected = windowVal.startsWith('sprint:')
  const currentSprintId = isSprintSelected ? windowVal.replace('sprint:', '') : ''

  return (
    <div className={styles.container}>
      <div className={styles.chips} aria-label="Janela temporal">
        {standardWindows.map((w) => (
          <button
            key={w.id}
            type="button"
            className={`${styles.chipBtn} ${windowVal === w.id ? styles.chipActive : ''}`}
            onClick={() => onWindowChange(w.id)}
          >
            {w.label}
          </button>
        ))}

        {sprints.length > 0 ? (
          <select
            className={`${styles.sprintSelect} ${isSprintSelected ? styles.sprintSelectActive : ''}`}
            value={currentSprintId}
            onChange={(e) => {
              const val = e.target.value
              if (val) {
                onWindowChange(`sprint:${val}`)
              } else {
                onWindowChange('30d')
              }
            }}
            aria-label="Selecionar Sprint"
          >
            <option value="">Sprints...</option>
            {sprints.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        ) : (
          <button
            type="button"
            className={`${styles.chipBtn} ${windowVal === 'sprint' ? styles.chipActive : ''}`}
            onClick={() => setModalOpen(true)}
            title="Criar sprints para filtrar"
          >
            + Sprint
          </button>
        )}

        {showManageButton && (
          <button
            type="button"
            className={styles.manageBtn}
            onClick={() => setModalOpen(true)}
            title="Gerenciar Sprints"
            aria-label="Gerenciar Sprints"
          >
            <FontAwesomeIcon icon={sprints.length > 0 ? faCalendarDays : faPlus} />
          </button>
        )}
      </div>

      <SprintModal
        projectId={projectId}
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSelectSprint={(sprintId) => onWindowChange(`sprint:${sprintId}`)}
      />
    </div>
  )
}
