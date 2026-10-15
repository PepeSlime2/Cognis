import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faDatabase,
  faRotateRight,
  faFileLines,
  faGear,
  faChevronRight,
  faTableColumns,
  faClock,
  faUsers,
  faLink,
} from '@fortawesome/free-solid-svg-icons'
import type { ProviderConnection, SyncRun } from '../../api/client'
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
  syncRun?: SyncRun | null
  hasActiveSource?: boolean
  hasGithubSource?: boolean
  autoSync?: boolean
  syncIntervalMin?: number
  nextSyncAt?: string | null
  onUpdateSyncInterval?: (autoSync: boolean, intervalMin: number) => void
  hasTrelloSource?: boolean
  hasUnconfirmedColumns?: boolean
  onOpenColumnsModal?: () => void
  onOpenPeopleModal?: () => void
  onOpenLinksModal?: () => void
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
  syncRun,
  hasActiveSource: hasActiveSourceProp,
  hasGithubSource = false,
  autoSync = false,
  syncIntervalMin = 60,
  nextSyncAt,
  onUpdateSyncInterval,
  hasTrelloSource = false,
  hasUnconfirmedColumns = false,
  onOpenColumnsModal,
  onOpenPeopleModal,
  onOpenLinksModal,
}: LeftDockProps) => {
  const navigate = useNavigate()
  const hasActiveSource = hasActiveSourceProp ?? hasGithubSource
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    sources: true,
    sync: true,
    reports: false,
    settings: false,
  })
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
                  value={!autoSync ? 'manual' : String(syncIntervalMin)}
                  onChange={(e) => {
                    if (onUpdateSyncInterval) {
                      const val = e.target.value
                      if (val === 'manual') {
                        onUpdateSyncInterval(false, syncIntervalMin || 60)
                      } else {
                        onUpdateSyncInterval(true, Number(val))
                      }
                    }
                  }}
                >
                  <option value="manual">Manual (Desativado)</option>
                  <option value="15">A cada 15 min</option>
                  <option value="30">A cada 30 min</option>
                  <option value="60">A cada 1 hora (padrão)</option>
                  <option value="360">A cada 6 horas</option>
                  <option value="1440">A cada 24 horas</option>
                </select>
                {autoSync && nextSyncAt && (
                  <span className={styles.nextSyncInfo}>
                    <FontAwesomeIcon icon={faClock} />
                    Próxima: {(() => {
                      try {
                        return new Intl.DateTimeFormat('pt-BR', {
                          timeZone: 'America/Sao_Paulo',
                          day: '2-digit',
                          month: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                        }).format(new Date(nextSyncAt))
                      } catch {
                        return 'Programada'
                      }
                    })()}
                  </span>
                )}
              </div>

              <button
                type="button"
                className={styles.syncBtn}
                onClick={onSync}
                disabled={!hasActiveSource || syncInProgress}
                title={!hasActiveSource ? 'Conecte fontes para sincronizar' : 'Iniciar coleta'}
              >
                <FontAwesomeIcon icon={faRotateRight} spin={syncInProgress} />
                <span>{syncInProgress ? 'Sincronizando…' : 'Sincronizar agora'}</span>
              </button>

              {(syncRun || lastRunStatus) && (
                <div className={styles.runStatusCard} role="status">
                  <div className={styles.runHeaderRow}>
                    <strong style={{ fontSize: '11px', color: '#ffffff' }}>Coleta</strong>
                    {(() => {
                      const st = syncRun?.status || lastRunStatus?.status
                      switch (st) {
                        case 'queued':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgeQueued}`}>Em fila</span>
                        case 'running':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgeRunning}`}>Sincronizando</span>
                        case 'success':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgeSuccess}`}>Sucesso</span>
                        case 'partial':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgePartial}`}>Parcial</span>
                        case 'failed':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgeFailed}`}>Falha</span>
                        case 'paused_rate_limit':
                          return <span className={`${styles.statusBadge} ${styles.statusBadgePausedRateLimit}`}>Rate Limit</span>
                        default:
                          return st ? <span className={styles.statusBadge}>{st}</span> : null
                      }
                    })()}
                  </div>

                  <span className={styles.runMessage}>
                    {syncRun?.progress?.message || lastRunStatus?.message || 'Processando dados...'}
                  </span>

                  {(() => {
                    const done = syncRun?.progress?.done ?? lastRunStatus?.done ?? 0
                    const total = syncRun?.progress?.total ?? lastRunStatus?.total ?? 0
                    if (total > 0) {
                      const pct = Math.min(100, Math.round((done / total) * 100))
                      return (
                        <div className={styles.progressBarContainer}>
                          <div
                            className={styles.progressBarFill}
                            style={{ width: `${pct}%` }}
                            title={`${pct}% concluído (${done}/${total})`}
                          />
                        </div>
                      )
                    }
                    return null
                  })()}

                  {syncRun?.errors && syncRun.errors.length > 0 && (
                    <div className={styles.errorList} role="alert">
                      {syncRun.errors.map((err, idx) => (
                        <div key={idx} className={styles.errorItem}>
                          • {err.message || err.code}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {(hasTrelloSource || onOpenColumnsModal) && onOpenColumnsModal && (
                <button
                  type="button"
                  className={styles.columnsBtn}
                  onClick={onOpenColumnsModal}
                  title="Configurar mapeamento de colunas do Trello"
                >
                  <FontAwesomeIcon icon={faTableColumns} />
                  <span>Mapear Colunas</span>
                  {hasUnconfirmedColumns && <span className={styles.unconfirmedDot} title="Colunas pendentes de confirmação" />}
                </button>
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
              {onOpenPeopleModal && (
                <button type="button" className={styles.settingsNavBtn} onClick={onOpenPeopleModal}>
                  <FontAwesomeIcon icon={faUsers} />
                  <span>Pessoas</span>
                </button>
              )}
              {onOpenLinksModal && (
                <button type="button" className={styles.settingsNavBtn} onClick={onOpenLinksModal}>
                  <FontAwesomeIcon icon={faLink} />
                  <span>Vínculos Trello ↔ GitHub</span>
                </button>
              )}
            </div>
          )}
        </section>
      </div>
    </aside>
  )
}

export default LeftDock
