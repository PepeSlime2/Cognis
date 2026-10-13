import type { RefObject } from 'react'
import { useNavigate } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
  faBars,
  faExpand,
  faCompress,
  faMagnifyingGlass,
  faSliders,
  faCalendarDays,
  faRightFromBracket,
} from '@fortawesome/free-solid-svg-icons'
import type { GraphLayer, ProjectSummary } from '../../api/client'
import cognisLogo from '../../assets/CognisLogotipo.png'
import styles from './graphTopBar.module.css'

const layers: Array<{ id: GraphLayer; label: string }> = [
  { id: 'all', label: 'Todos' },
  { id: 'people', label: 'Pessoas' },
  { id: 'tasks', label: 'Atividades' },
  { id: 'artifacts', label: 'Artefatos' },
]

const windows = [
  { id: '7d', label: '7d' },
  { id: '14d', label: '14d' },
  { id: '30d', label: '30d' },
  { id: '90d', label: '90d' },
  { id: 'sprint', label: 'Sprint' },
]

type GraphTopBarProps = {
  projectId: string
  projects?: ProjectSummary[]
  leftOpen: boolean
  onToggleLeft: () => void
  rightOpen: boolean
  onToggleRight: () => void
  focusMode: boolean
  onToggleFocus: () => void
  windowVal: string
  onWindowChange: (w: string) => void
  layer: GraphLayer
  onLayerChange: (l: GraphLayer) => void
  searchQuery: string
  onSearchChange: (q: string) => void
  onSearchSubmit: () => void
  syncStatus?: { status: string; message: string; running: boolean; isError?: boolean }
  onLogout: () => void | Promise<void>
  searchInputRef: RefObject<HTMLInputElement | null>
}

const GraphTopBar = ({
  projectId,
  projects,
  leftOpen,
  onToggleLeft,
  rightOpen,
  onToggleRight,
  focusMode,
  onToggleFocus,
  windowVal,
  onWindowChange,
  layer,
  onLayerChange,
  searchQuery,
  onSearchChange,
  onSearchSubmit,
  syncStatus,
  onLogout,
  searchInputRef,
}: GraphTopBarProps) => {
  const navigate = useNavigate()

  return (
    <header className={styles.topBar} role="banner">
      <div className={styles.leftSection}>
        <button
          type="button"
          className={`${styles.menuToggleBtn} ${leftOpen ? styles.iconBtnActive : ''}`}
          onClick={onToggleLeft}
          aria-label={leftOpen ? 'Recolher menu lateral' : 'Expandir menu lateral'}
          title="Alternar menu lateral ([)"
        >
          <FontAwesomeIcon icon={faBars} />
        </button>

        <div className={styles.brand} onClick={() => navigate('/')} role="button" tabIndex={0} title="COGNIS">
          <img src={cognisLogo} alt="COGNIS" className={styles.brandLogo} />
        </div>
      </div>

      <div className={styles.centerSection}>
        <div className={styles.layerChips} aria-label="Camadas do grafo">
          {layers.map((l) => (
            <button
              key={l.id}
              type="button"
              className={`${styles.chipBtn} ${layer === l.id ? styles.chipActive : ''}`}
              onClick={() => onLayerChange(l.id)}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.rightSection}>
        <div className={styles.selectorGroup}>
          <label htmlFor="topbar-project-select" className={styles.fieldLabel}>
            Projeto Ativo:
          </label>
          <select
            id="topbar-project-select"
            className={styles.projectSelect}
            value={projectId}
            onChange={(e) => {
              if (e.target.value) navigate(`/p/${e.target.value}`)
              else navigate('/')
            }}
            aria-label="Selecionar projeto"
          >
            {projects?.map((proj) => (
              <option key={proj.id} value={proj.id}>
                {proj.name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.selectorGroup}>
          <span className={styles.fieldLabel}>
            <FontAwesomeIcon icon={faCalendarDays} style={{ marginRight: 4 }} />
            Período:
          </span>
          <div className={styles.windowChips} aria-label="Janela temporal">
            {windows.map((w) => (
              <button
                key={w.id}
                type="button"
                className={`${styles.chipBtn} ${windowVal === w.id ? styles.chipActive : ''}`}
                onClick={() => onWindowChange(w.id)}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>

        <form
          className={styles.searchBox}
          onSubmit={(e) => {
            e.preventDefault()
            onSearchSubmit()
          }}
        >
          <FontAwesomeIcon icon={faMagnifyingGlass} className={styles.searchIcon} />
          <input
            ref={searchInputRef}
            className={styles.searchInput}
            type="search"
            placeholder="Buscar no grafo... (/)"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            aria-label="Buscar nó no grafo (atalho /)"
          />
        </form>

        {syncStatus && (
          <div className={styles.syncIndicator} role="status">
            <span
              className={`${styles.syncDot} ${
                syncStatus.running
                  ? styles.dotRunning
                  : syncStatus.isError
                  ? styles.dotError
                  : styles.dotSuccess
              }`}
            />
            <span className={styles.syncText}>{syncStatus.message}</span>
          </div>
        )}

        <button
          type="button"
          className={`${styles.iconBtn} ${focusMode ? styles.iconBtnActive : ''}`}
          onClick={onToggleFocus}
          aria-label={focusMode ? 'Sair do modo foco (Esc)' : 'Entrar no modo foco'}
          title={focusMode ? 'Sair do modo foco (Esc)' : 'Modo tela cheia'}
        >
          <FontAwesomeIcon icon={focusMode ? faCompress : faExpand} />
        </button>

        <button
          type="button"
          className={`${styles.iconBtn} ${rightOpen ? styles.iconBtnActive : ''}`}
          onClick={onToggleRight}
          aria-label={rightOpen ? 'Ocultar métricas e painel' : 'Exibir métricas e painel'}
          title="Alternar métricas e painel (])"
        >
          <FontAwesomeIcon icon={faSliders} />
        </button>

        <button
          type="button"
          className={styles.logoutBtn}
          onClick={() => void onLogout()}
          aria-label="Sair da conta"
          title="Sair"
        >
          <FontAwesomeIcon icon={faRightFromBracket} />
          <span>Sair</span>
        </button>
      </div>
    </header>
  )
}

export default GraphTopBar
