import { useState } from 'react'
import styles from './graphLegend.module.css'

const GraphLegend = () => {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside className={styles.legendContainer} aria-label="Legenda do grafo">
      <div
        className={styles.legendHeader}
        onClick={() => setCollapsed(!collapsed)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setCollapsed(!collapsed)
          }
        }}
      >
        <span className={styles.legendTitle}>Legenda</span>
        <button
          type="button"
          className={styles.toggleBtn}
          aria-label={collapsed ? 'Expandir legenda' : 'Recolher legenda'}
        >
          {collapsed ? '▲' : '▼'}
        </button>
      </div>

      {!collapsed && (
        <div className={styles.legendBody}>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.personColor}`} /> Pessoas
          </span>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.taskColor}`} /> Issues
          </span>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.prColor}`} /> Pull requests
          </span>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.repoColor}`} /> Repositórios
          </span>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.moduleColor}`} /> Módulos
          </span>
          <span className={styles.legendItem}>
            <i className={`${styles.legendDot} ${styles.columnColor}`} /> Colunas
          </span>
        </div>
      )}
    </aside>
  )
}

export default GraphLegend
