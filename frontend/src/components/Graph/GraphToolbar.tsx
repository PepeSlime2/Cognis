import styles from './graphToolbar.module.css'

type GraphToolbarProps = {
  sizeBy: string
  onSizeByChange: (val: string) => void
  colorBy: string
  onColorByChange: (val: string) => void
  layout: string
  onLayoutChange: (val: string) => void
  minWeight: number
  onMinWeightChange: (val: number) => void
  includeBots: boolean
  onIncludeBotsChange: (val: boolean) => void
  showLabels: boolean
  onShowLabelsChange: (val: boolean) => void
  pathMode: boolean
  onTogglePathMode: () => void
  onFit: () => void
  onExportPng: () => void
  fxLevel: 'full' | 'lite' | 'off'
  onFxLevelChange: (val: 'full' | 'lite' | 'off') => void
  onReset: () => void
  disabled?: boolean
}

const GraphToolbar = ({
  sizeBy,
  onSizeByChange,
  colorBy,
  onColorByChange,
  layout,
  onLayoutChange,
  minWeight,
  onMinWeightChange,
  includeBots,
  onIncludeBotsChange,
  showLabels,
  onShowLabelsChange,
  pathMode,
  onTogglePathMode,
  onFit,
  onExportPng,
  fxLevel,
  onFxLevelChange,
  onReset,
  disabled = false,
}: GraphToolbarProps) => {
  return (
    <nav className={styles.toolbar} aria-label="Ferramentas do grafo">
      <div className={styles.controlGroup}>
        <label className={styles.controlLabel} htmlFor="size-select">
          Tamanho:
        </label>
        <select
          id="size-select"
          className={styles.controlSelect}
          value={sizeBy}
          onChange={(e) => onSizeByChange(e.target.value)}
          disabled={disabled}
        >
          <option value="degree">Grau (Degree)</option>
          <option value="weighted_degree">Grau ponderado</option>
          <option value="betweenness">Intermediação</option>
          <option value="closeness">Proximidade</option>
          <option value="pagerank">PageRank</option>
          <option value="participation">Participação</option>
          <option value="uniforme">Uniforme</option>
        </select>
      </div>

      <div className={styles.controlGroup}>
        <label className={styles.controlLabel} htmlFor="color-select">
          Cor:
        </label>
        <select
          id="color-select"
          className={styles.controlSelect}
          value={colorBy}
          onChange={(e) => onColorByChange(e.target.value)}
          disabled={disabled}
        >
          <option value="comunidade">Comunidade</option>
          <option value="tipo">Tipo</option>
          <option value="risco">Risco</option>
          <option value="categoria da tarefa">Categoria de tarefa</option>
        </select>
      </div>

      <div className={styles.controlGroup}>
        <label className={styles.controlLabel} htmlFor="layout-select">
          Layout:
        </label>
        <select
          id="layout-select"
          className={styles.controlSelect}
          value={layout}
          onChange={(e) => onLayoutChange(e.target.value)}
          disabled={disabled}
        >
          <option value="fcose">fCoSE (Força)</option>
          <option value="concentric">Concêntrico</option>
          <option value="circle">Círculo</option>
          <option value="grid">Grade</option>
          <option value="breadthfirst">Hierárquico</option>
        </select>
      </div>

      <div className={styles.separator} />

      <div className={styles.controlGroup}>
        <label className={styles.controlLabel} htmlFor="weight-slider">
          Peso mín.:
        </label>
        <input
          id="weight-slider"
          type="range"
          min={1}
          max={5}
          step={1}
          className={styles.rangeInput}
          value={minWeight}
          onChange={(e) => onMinWeightChange(Number(e.target.value))}
          disabled={disabled}
          aria-label="Filtrar por peso mínimo de aresta"
        />
        <output className={styles.rangeOutput}>{minWeight}+</output>
      </div>

      <label className={styles.checkboxLabel}>
        <input
          type="checkbox"
          className={styles.checkboxInput}
          checked={includeBots}
          onChange={(e) => onIncludeBotsChange(e.target.checked)}
          disabled={disabled}
        />
        Bots
      </label>

      <label className={styles.checkboxLabel}>
        <input
          type="checkbox"
          className={styles.checkboxInput}
          checked={showLabels}
          onChange={(e) => onShowLabelsChange(e.target.checked)}
          disabled={disabled}
        />
        Rótulos
      </label>

      <div className={styles.separator} />

      <button
        type="button"
        className={`${styles.toolBtn} ${pathMode ? styles.toolBtnActive : ''}`}
        onClick={onTogglePathMode}
        disabled={disabled}
        title="Selecione 2 nós para destacar o caminho"
      >
        Caminho mais curto
      </button>

      <button
        type="button"
        className={styles.toolBtn}
        onClick={onFit}
        disabled={disabled}
        title="Ajustar grafo à tela (atalho F)"
      >
        Ajustar à tela
      </button>

      <button
        type="button"
        className={styles.toolBtn}
        onClick={onExportPng}
        disabled={disabled}
        title="Exportar imagem em alta resolução"
      >
        Exportar PNG
      </button>

      <div className={styles.controlGroup}>
        <label className={styles.controlLabel} htmlFor="fx-select">
          Efeitos:
        </label>
        <select
          id="fx-select"
          className={styles.controlSelect}
          value={fxLevel}
          onChange={(e) => onFxLevelChange(e.target.value as 'full' | 'lite' | 'off')}
        >
          <option value="full">Completo</option>
          <option value="lite">Leve</option>
          <option value="off">Desligado</option>
        </select>
      </div>

      <button
        type="button"
        className={styles.toolBtn}
        onClick={onReset}
        disabled={disabled}
        title="Redefinir visualização e filtros"
      >
        Resetar
      </button>
    </nav>
  )
}

export default GraphToolbar
