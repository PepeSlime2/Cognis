import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faArrowLeft,
  faWandMagicSparkles,
  faChartSimple,
  faUsers,
  faDiagramProject,
} from '@fortawesome/free-solid-svg-icons'
import { WindowPicker } from '../../components/WindowPicker/WindowPicker'
import AnalysisPanel from '../../components/Insights/AnalysisPanel'
import styles from './analysisPage.module.css'

export const AnalysisPage = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [selectedWindow, setSelectedWindow] = useState('30d')

  if (!projectId) {
    return (
      <div className={styles.pageContainer}>
        <div className={styles.contentWrapper}>
          <p>Projeto não selecionado.</p>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.pageContainer}>
      <header className={styles.topBar}>
        <div className={styles.topLeft}>
          <Link to={`/p/${projectId}`} className={styles.backLink}>
            <FontAwesomeIcon icon={faArrowLeft} />
            <span>Grafo</span>
          </Link>
          <h1 className={styles.pageTitle}>
            <FontAwesomeIcon icon={faWandMagicSparkles} />
            <span>Análise de IA & Síntese</span>
          </h1>
        </div>

        <div className={styles.topRight}>
          <WindowPicker
            projectId={projectId}
            windowVal={selectedWindow}
            onWindowChange={setSelectedWindow}
          />

          <Link to={`/p/${projectId}/metrics`} className={styles.navLinkBtn}>
            <FontAwesomeIcon icon={faChartSimple} />
            <span>Métricas</span>
          </Link>

          <Link to={`/p/${projectId}/people`} className={styles.navLinkBtn}>
            <FontAwesomeIcon icon={faUsers} />
            <span>Pessoas</span>
          </Link>

          <Link to={`/p/${projectId}`} className={styles.navLinkBtn}>
            <FontAwesomeIcon icon={faDiagramProject} />
            <span>Ver Grafo</span>
          </Link>
        </div>
      </header>

      <main className={styles.contentWrapper}>
        <div className={styles.panelWrapper}>
          <AnalysisPanel
            projectId={projectId}
            windowVal={selectedWindow}
          />
        </div>
      </main>
    </div>
  )
}

export default AnalysisPage
