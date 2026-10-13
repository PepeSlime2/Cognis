import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faDatabase,
  faRotateRight,
  faFileLines,
  faGear,
  faChevronRight,
} from '@fortawesome/free-solid-svg-icons'
import type { ProviderConnection } from '../../api/client'
import iconTrello from '../../assets/trelloicon.png'
import iconGitHub from '../../assets/github-white-icon.webp'
import styles from './leftDock.module.css'

type LeftDockProps = {
  isOpen: boolean
  onOpenSection: (section: string) => void
  connections?: Record<string, ProviderConnection>
  onConnectGithub: () => void
  onConnectTrello: () => void
  onSync: () => void
  syncInProgress: boolean
  lastRunStatus?: { status: string; message?: string; done?: number; total?: number }
  hasGithubSource: boolean
}

const LeftDock = ({
  isOpen,
  onOpenSection,
  connections = {},
  onConnectGithub,
  onConnectTrello,
  onSync,
  syncInProgress,
  lastRunStatus,
  hasGithubSource,
}: LeftDockProps) => {
  const navigate = useNavigate()
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    sources: true,
    sync: true,
    reports: false,
    settings: false,
  })
  const [syncInterval, setSyncInterval] = useState('1h')
  const [reportFeedback, setReportFeedback] = useState<string | null>(null)

  const toggleSection = (section: string) => {
    setOpenSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }))
  }

  const handleRailClick = (section: string) => {
    setOpenSections((prev) => ({
      ...prev,
      [section]: true,
    }))
    onOpenSection(section)
  }

  const handleReportClick = (name: string) => {
    setReportFeedback(`Relatório "${name}" selecionado (em breve geração via IA).`)
    setTimeout(() => setReportFeedback(null), 3500)
  }

  if (!isOpen) {
    return (
      <aside className={styles.dock} aria-label="Menu lateral recolhido">
        <div className={styles.rail}>
          <button
            type="button"
            className={`${styles.railIconBtn} ${openSections.sources ? styles.railIconActive : ''}`}
            onClick={() => handleRailClick('sources')}
            aria-label="Abrir seção Fontes de Dados"
            title="Fontes de Dados"
          >
            <FontAwesomeIcon icon={faDatabase} />
          </button>

          <button
            type="button"
            className={`${styles.railIconBtn} ${openSections.sync ? styles.railIconActive : ''}`}
            onClick={() => handleRailClick('sync')}
            aria-label="Abrir seção Coleta"
            title="Coleta e Sincronização"
          >
            <FontAwesomeIcon icon={faRotateRight} />
          </button>

          <button
            type="button"
            className={`${styles.railIconBtn} ${openSections.reports ? styles.railIconActive : ''}`}
            onClick={() => handleRailClick('reports')}
            aria-label="Abrir seção Relatórios"
            title="Relatórios"
          >
            <FontAwesomeIcon icon={faFileLines} />
          </button>

          <button
            type="button"
            className={`${styles.railIconBtn} ${openSections.settings ? styles.railIconActive : ''}`}
            onClick={() => handleRailClick('settings')}
            aria-label="Abrir seção Configurações"
            title="Configurações"
          >
            <FontAwesomeIcon icon={faGear} />
          </button>
        </div>
      </aside>
    )
  }

  return (
    <aside className={styles.dock} aria-label="Menu lateral de fontes e coleta">
      <div className={styles.expanded}>
        {/* Seção 1: Fontes de Dados */}
        <section className={styles.accordionSection}>
          <button
            type="button"
            className={styles.accordionHeader}
            onClick={() => toggleSection('sources')}
            aria-expanded={openSections.sources}
          >
            <div className={styles.headerLeft}>
              <FontAwesomeIcon icon={faDatabase} className={styles.headerIcon} />
              <span>Fontes de Dados</span>
            </div>
            <FontAwesomeIcon
              icon={faChevronRight}
              className={`${styles.accordionChevron} ${
                openSections.sources ? styles.chevronExpanded : ''
              }`}
            />
          </button>

          {openSections.sources && (
            <div className={styles.accordionBody}>
              <button
                type="button"
                className={styles.sourceBtn}
                onClick={onConnectGithub}
              >
                <div className={styles.sourceInfo}>
                  <img src={iconGitHub} alt="GitHub" className={styles.sourceLogo} />
                  <span>GitHub</span>
                </div>
                <div className={styles.sourceStatus}>
                  <span
                    className={
                      connections.github
                        ? styles.statusDotConnected
                        : styles.statusDotDisconnected
                    }
                  />
                  <span>
                    {connections.github
                      ? connections.github.username
                      : 'Conectar'}
                  </span>
                </div>
              </button>

              <button
                type="button"
                className={styles.sourceBtn}
                onClick={onConnectTrello}
              >
                <div className={styles.sourceInfo}>
                  <img src={iconTrello} alt="Trello" className={styles.sourceLogo} />
                  <span>Trello</span>
                </div>
                <div className={styles.sourceStatus}>
                  <span
                    className={
                      connections.trello
                        ? styles.statusDotConnected
                        : styles.statusDotDisconnected
                    }
                  />
                  <span>
                    {connections.trello
                      ? connections.trello.username
                      : 'Conectar'}
                  </span>
                </div>
              </button>
            </div>
          )}
        </section>

        {/* Seção 2: Coleta */}
        <section className={styles.accordionSection}>
          <button
            type="button"
            className={styles.accordionHeader}
            onClick={() => toggleSection('sync')}
            aria-expanded={openSections.sync}
          >
            <div className={styles.headerLeft}>
              <FontAwesomeIcon icon={faRotateRight} className={styles.headerIcon} />
              <span>Coleta</span>
            </div>
            <FontAwesomeIcon
              icon={faChevronRight}
              className={`${styles.accordionChevron} ${
                openSections.sync ? styles.chevronExpanded : ''
              }`}
            />
          </button>

          {openSections.sync && (
            <div className={styles.accordionBody}>
              <div className={styles.fieldRow}>
                <label className={styles.fieldLabel} htmlFor="sync-interval">
                  Intervalo Automático
                </label>
                <select
                  id="sync-interval"
                  className={styles.selectInput}
                  value={syncInterval}
                  onChange={(e) => setSyncInterval(e.target.value)}
                >
                  <option value="manual">Manual</option>
                  <option value="15m">A cada 15 min</option>
                  <option value="30m">A cada 30 min</option>
                  <option value="1h">A cada 1 hora</option>
                  <option value="6h">A cada 6 horas</option>
                  <option value="24h">A cada 24 horas</option>
                </select>
              </div>

              <button
                type="button"
                className={styles.syncBtn}
                onClick={onSync}
                disabled={!hasGithubSource || syncInProgress}
              >
                <FontAwesomeIcon icon={faRotateRight} />
                <span>{syncInProgress ? 'Sincronizando…' : 'Sincronizar agora'}</span>
              </button>

              {lastRunStatus && (
                <div className={styles.runStatusCard} role="status">
                  <strong>Status: {lastRunStatus.status}</strong>
                  <span>{lastRunStatus.message}</span>
                  {lastRunStatus.total !== undefined && lastRunStatus.total > 0 && (
                    <div className={styles.progressBarContainer}>
                      <div
                        className={styles.progressBarFill}
                        style={{
                          width: `${Math.round(
                            ((lastRunStatus.done ?? 0) / lastRunStatus.total) * 100,
                          )}%`,
                        }}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Seção 3: Relatórios */}
        <section className={styles.accordionSection}>
          <button
            type="button"
            className={styles.accordionHeader}
            onClick={() => toggleSection('reports')}
            aria-expanded={openSections.reports}
          >
            <div className={styles.headerLeft}>
              <FontAwesomeIcon icon={faFileLines} className={styles.headerIcon} />
              <span>Relatórios</span>
            </div>
            <FontAwesomeIcon
              icon={faChevronRight}
              className={`${styles.accordionChevron} ${
                openSections.reports ? styles.chevronExpanded : ''
              }`}
            />
          </button>

          {openSections.reports && (
            <div className={styles.accordionBody}>
              <div className={styles.reportList}>
                {['Sprint', 'Gerencial', 'Individual', 'Gargalos', 'Colaboração'].map(
                  (name) => (
                    <button
                      key={name}
                      type="button"
                      className={styles.reportItem}
                      onClick={() => handleReportClick(name)}
                    >
                      <span>{name}</span>
                      <FontAwesomeIcon icon={faChevronRight} />
                    </button>
                  ),
                )}
              </div>
              {reportFeedback && (
                <p className={styles.serviceError} role="status">
                  {reportFeedback}
                </p>
              )}
            </div>
          )}
        </section>

        {/* Seção 4: Configurações */}
        <section className={styles.accordionSection}>
          <button
            type="button"
            className={styles.accordionHeader}
            onClick={() => toggleSection('settings')}
            aria-expanded={openSections.settings}
          >
            <div className={styles.headerLeft}>
              <FontAwesomeIcon icon={faGear} className={styles.headerIcon} />
              <span>Configurações</span>
            </div>
            <FontAwesomeIcon
              icon={faChevronRight}
              className={`${styles.accordionChevron} ${
                openSections.settings ? styles.chevronExpanded : ''
              }`}
            />
          </button>

          {openSections.settings && (
            <div className={styles.accordionBody}>
              <button
                type="button"
                className={styles.settingsNavBtn}
                onClick={() => navigate('/settings')}
              >
                <FontAwesomeIcon icon={faGear} />
                <span>Configurações do Projeto</span>
              </button>
            </div>
          )}
        </section>
      </div>
    </aside>
  )
}

export default LeftDock
