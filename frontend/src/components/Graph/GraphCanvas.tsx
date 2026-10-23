import { useEffect, useMemo, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, LayoutOptions, StylesheetJson } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import type { GraphNodeData, MetricResult, ProjectGraph } from '../../api/client'
import type { GraphSelection } from './types'
import styles from './graph.module.css'

cytoscape.use(fcose)

const communityColors = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ec4899',
  '#8b5cf6',
  '#06b6d4',
  '#f97316',
  '#14b8a6',
  '#eab308',
  '#3b82f6',
]

function svgToUri(svgString: string): string {

  return `data:image/svg+xml;utf8,${encodeURIComponent(svgString)}`
}

const personSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#8FBF78" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
)

const taskSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#65B5D9" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>'
)

const prSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#C17BC7" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>'
)

const issueSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#E5A13E" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
)

const repoSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#4A8B71" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>'
)

const commitSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#BDB4A2" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>'
)

const moduleSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#8FBF78" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>'
)

const columnSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#D5A04A" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>'
)

const reviewSvg = svgToUri(
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 24 24" fill="none" stroke="#AD8BCF" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4c0-1.1.9-2 2-2h8a2 2 0 0 1 2 2v5Z"/><path d="m18 9 2 2 4-4"/></svg>'
)

function syncNodeSizesWithZoom(cy: Core | null) {
  if (!cy) return
  const z = cy.zoom()
  if (!z || z <= 0) return
  cy.batch(() => {
    cy.nodes().forEach((node) => {
      const metric = Number(node.data('size_metric') ?? 0)
      const baseSize = 34 + metric * 14
      const targetSize = Math.max(8, Math.min(160, baseSize / z))
      node.style('width', `${targetSize}px`)
      node.style('height', `${targetSize}px`)
    })
  })
}

const graphStyle: StylesheetJson = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      color: '#E9E0CE',
      'font-family': 'Plus Jakarta Sans, sans-serif',
      'font-size': '11px',
      'font-weight': 600,
      'text-wrap': 'ellipsis',
      'text-max-width': '125px',
      'text-valign': 'bottom',
      'text-margin-y': 7,
      'text-background-color': '#182923',
      'text-background-opacity': 0.85,
      'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle',
      shape: 'rectangle',
      width: 'mapData(size_metric, 0, 1, 34, 48)',
      height: 'mapData(size_metric, 0, 1, 34, 48)',
      'background-color': 'transparent',
      'background-opacity': 0,
      'background-fit': 'contain',
      'background-width': '100%',
      'background-height': '100%',
      'background-clip': 'none',
      'background-position-x': '50%',
      'background-position-y': '50%',
      'border-width': 0,
      'border-opacity': 0,
      'underlay-opacity': 0,
      'overlay-opacity': 0,
    },
  },
  {
    selector: 'node[type = "person"]',
    style: {
      'background-image': personSvg,
    },
  },
  {
    selector: 'node[type = "task"]',
    style: {
      'background-image': taskSvg,
    },
  },
  {
    selector: 'node[type = "pr"]',
    style: {
      'background-image': prSvg,
    },
  },
  {
    selector: 'node[type = "issue"]',
    style: {
      'background-image': issueSvg,
    },
  },
  {
    selector: 'node[type = "commit"]',
    style: {
      'background-image': commitSvg,
    },
  },
  {
    selector: 'node[type = "repo"]',
    style: {
      'background-image': repoSvg,
    },
  },
  {
    selector: 'node[type = "module"]',
    style: {
      'background-image': moduleSvg,
    },
  },
  {
    selector: 'node[type = "column"]',
    style: {
      'background-image': columnSvg,
    },
  },
  {
    selector: 'node[type = "review"]',
    style: {
      'background-image': reviewSvg,
    },
  },
  {
    selector: 'node:selected',
    style: {
      label: 'data(label)',
      'border-width': 0,
      'underlay-opacity': 0,
      'overlay-opacity': 0,
      'text-background-color': '#C5A15D',
      'text-background-opacity': 1,
      'text-background-padding': '4px',
      color: '#121E19',
      'font-weight': 800,
    },
  },
  {
    selector: 'node.path-node',
    style: {
      label: 'data(label)',
      'border-width': 0,
      'underlay-opacity': 0,
      'overlay-opacity': 0,
      'text-background-color': '#C5A15D',
      'text-background-opacity': 1,
      'text-background-padding': '4px',
      color: '#121E19',
      'font-weight': 800,
    },
  },
  {
    selector: 'edge',
    style: {
      width: 'mapData(weight, 1, 8, 1.4, 4.5)',
      'line-color': '#795638',
      'target-arrow-color': '#795638',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      opacity: 0.76,
      label: 'data(type)',
      color: '#BDB4A2',
      'font-size': '8px',
      'font-family': 'Plus Jakarta Sans, sans-serif',
      'text-rotation': 'autorotate',
      'text-background-color': '#182923',
      'text-background-opacity': 0.9,
      'text-background-padding': '3px',
    },
  },
  {
    selector: 'edge[type = "review"]',
    style: {
      'line-color': '#B99BCB',
      'target-arrow-color': '#B99BCB',
      'line-style': 'dashed',
      opacity: 0.88,
    },
  },
  {
    selector: 'edge[type = "comment"], edge[type = "abriu"], edge[type = "mesclou"], edge[type = "realizou"]',
    style: {
      'line-color': '#9BBF8B',
      'target-arrow-color': '#9BBF8B',
      opacity: 0.88,
    },
  },
  {
    selector: 'edge[type = "bloqueada_por"], edge[type = "na_coluna"]',
    style: {
      'line-color': '#A69D8D',
      'target-arrow-color': '#A69D8D',
      'line-style': 'dashed',
      opacity: 0.85,
    },
  },
  {
    selector: 'edge[type = "no_repositorio"], edge[type = "alterou"], edge[type = "responsavel"], edge[type = "no_quadro"]',
    style: {
      'line-color': '#D2A04C',
      'target-arrow-color': '#D2A04C',
      opacity: 0.85,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      width: 5,
      'line-color': '#C5A15D',
      'target-arrow-color': '#C5A15D',
      opacity: 1,
    },
  },
  {
    selector: 'edge.path-edge',
    style: {
      width: 5.5,
      'line-color': '#C5A15D',
      'target-arrow-color': '#C5A15D',
      opacity: 1,
    },
  },
  {
    selector: 'edge.hidden-by-weight',
    style: {
      display: 'none',
    },
  },
  {
    selector: 'node.signal-highlighted',
    style: {
      width: 'mapData(size_metric, 0, 1, 46, 64)',
      height: 'mapData(size_metric, 0, 1, 46, 64)',
      'border-width': 3,
      'border-color': '#f59e0b',
      'border-opacity': 1,
      'underlay-color': '#f59e0b',
      'underlay-padding': '10px',
      'underlay-opacity': 0.45,
      'underlay-shape': 'ellipse',
      'z-index': 999,
      opacity: 1,
    },
  },
  {
    selector: 'edge.signal-highlighted',
    style: {
      width: 4.5,
      'line-color': '#f59e0b',
      'target-arrow-color': '#f59e0b',
      opacity: 1,
      'z-index': 998,
    },
  },
  {
    selector: 'node.faded-by-signal',
    style: {
      opacity: 0.18,
    },
  },
  {
    selector: 'edge.faded-by-signal',
    style: {
      opacity: 0.07,
    },
  },
]

type GraphCanvasProps = {
  elements: ProjectGraph['elements']
  labelsVisible: boolean
  minWeight: number
  layoutName?: string
  pathMode?: boolean
  sizeBy?: string
  colorBy?: string
  metrics?: Record<string, MetricResult>
  highlightIds?: string[]
  onSelectionChange: (selection: GraphSelection) => void
  onClearHighlight?: () => void
  onGraphReady: (graph: Core | null) => void
}

const layoutOptions: LayoutOptions = {
  name: 'fcose',
  quality: 'default',
  animate: true,
  animationDuration: 500,
  randomize: true,
  fit: true,
  padding: 48,
  nodeRepulsion: 4800,
  idealEdgeLength: 130,
  numIter: 2500,
}

const GraphCanvas = ({
  elements,
  labelsVisible,
  minWeight,
  layoutName = 'fcose',
  pathMode = false,
  sizeBy = 'degree',
  colorBy = 'tipo',
  metrics,
  highlightIds = [],
  onSelectionChange,
  onClearHighlight,
  onGraphReady,
}: GraphCanvasProps) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Core | null>(null)
  const onSelectionChangeRef = useRef(onSelectionChange)
  const onClearHighlightRef = useRef(onClearHighlight)
  const pathModeRef = useRef(pathMode)
  const selectedNodesForPathRef = useRef<string[]>([])

  const graphElements = useMemo(
    () => [...elements.nodes, ...elements.edges] as ElementDefinition[],
    [elements.edges, elements.nodes],
  )

  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange
    onClearHighlightRef.current = onClearHighlight
  }, [onSelectionChange, onClearHighlight])

  useEffect(() => {
    pathModeRef.current = pathMode
    if (!pathMode && graphRef.current) {
      selectedNodesForPathRef.current = []
      graphRef.current.elements().removeClass('path-node path-edge')
    }
  }, [pathMode])

  useEffect(() => {
    if (!containerRef.current) return

    const graph = cytoscape({
      container: containerRef.current,
      elements: [],
      style: [...graphStyle],
      layout: { name: 'preset' },
      minZoom: 0.2,
      maxZoom: 3,
      boxSelectionEnabled: false,
    })
    graphRef.current = graph

    graph.on('tap', 'node', (event) => {
      const node = event.target
      if (pathModeRef.current) {
        const nodeId = node.id()
        const selected = selectedNodesForPathRef.current
        if (selected.length >= 2) {
          selectedNodesForPathRef.current = [nodeId]
          graph.elements().removeClass('path-node path-edge')
          node.addClass('path-node')
        } else {
          selected.push(nodeId)
          node.addClass('path-node')
          if (selected.length === 2) {
            const root = graph.getElementById(selected[0])
            const goal = graph.getElementById(selected[1])
            const aStarRes = graph.elements().aStar({ root, goal, directed: false })
            if (aStarRes.found) {
              aStarRes.path.addClass('path-node path-edge')
            }
          }
        }
      }

      onSelectionChangeRef.current({
        kind: 'node',
        id: node.id(),
        data: node.data() as GraphNodeData,
      })
    })

    graph.on('tap', 'edge', (event) => {
      const edge = event.target
      onSelectionChangeRef.current({
        kind: 'edge',
        id: edge.id(),
        data: edge.data() as Record<string, unknown>,
      })
    })

    graph.on('tap', (event) => {
      if (event.target === graph) {
        onSelectionChangeRef.current(null)
        onClearHighlightRef.current?.()
      }
    })

    let zoomRaf: number | null = null
    const handleZoom = () => {
      if (zoomRaf !== null) cancelAnimationFrame(zoomRaf)
      zoomRaf = requestAnimationFrame(() => {
        zoomRaf = null
        syncNodeSizesWithZoom(graph)
      })
    }
    graph.on('zoom', handleZoom)

    onGraphReady(graph)

    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        graphRef.current?.resize()
      })
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      if (zoomRaf !== null) cancelAnimationFrame(zoomRaf)
      resizeObserver.disconnect()
      onSelectionChangeRef.current(null)
      graphRef.current = null
      onGraphReady(null)
      graph.destroy()
    }
  }, [onGraphReady])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    const isInitial = graph.elements().length === 0

    graph.batch(() => {
      const newIds = new Set(
        graphElements
          .map((el) => el.data.id)
          .filter((id): id is string => typeof id === 'string'),
      )

      // Remover elementos que não existem mais
      graph.elements().forEach((el) => {
        if (!newIds.has(el.id())) {
          el.remove()
        }
      })

      // Adicionar elementos novos
      const toAdd = graphElements.filter((el) => {
        const id = el.data.id
        return typeof id === 'string' && graph.getElementById(id).length === 0
      })
      if (toAdd.length > 0) {
        graph.add(toAdd)
      }

      // Atualizar data() dos elementos persistentes
      graphElements.forEach((el) => {
        const id = el.data.id
        if (typeof id === 'string') {
          const existing = graph.getElementById(id)
          if (existing.length > 0 && el.data) {
            existing.data(el.data)
          }
        }
      })
    })

    graph.nodes().style('label', labelsVisible ? 'data(label)' : '')

    graph.edges().forEach((edge) => {
      const weight = Number(edge.data('weight') ?? 1)
      if (weight < minWeight) {
        edge.addClass('hidden-by-weight')
      } else {
        edge.removeClass('hidden-by-weight')
      }
    })

    if (graph.nodes().length > 0) {
      const layout =
        layoutName === 'fcose'
          ? graph.layout({
              ...layoutOptions,
              randomize: isInitial,
              animate: true,
              animationDuration: 650,
            })
          : graph.layout({
              name: layoutName,
              animate: true,
              animationDuration: 650,
            })

      layout.on('layoutstop', () => {
        syncNodeSizesWithZoom(graph)
      })
      layout.run()
    }
  }, [graphElements, labelsVisible, layoutName, minWeight])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.batch(() => {
      graph.edges().forEach((edge) => {
        const weight = Number(edge.data('weight') ?? 1)
        if (weight < minWeight) {
          edge.addClass('hidden-by-weight')
        } else {
          edge.removeClass('hidden-by-weight')
        }
      })
    })
  }, [minWeight])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.nodes().style('label', labelsVisible ? 'data(label)' : '')
  }, [labelsVisible])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    // 1. Reagir ao tamanho (sizeBy)
    const sizeMetricMap: Record<string, string> = {
      degree: 'graph.degree',
      weighted_degree: 'graph.weighted_degree',
      betweenness: 'graph.betweenness',
      closeness: 'graph.closeness',
      pagerank: 'graph.pagerank',
      participation: 'person.participation',
    }
    const targetMetricId = sizeMetricMap[sizeBy]

    const metricValues: Record<string, number> = {}
    if (targetMetricId && metrics?.[targetMetricId]?.values) {
      const rawVals = metrics[targetMetricId].values
      if (typeof rawVals === 'object') {
        Object.entries(rawVals).forEach(([k, v]) => {
          if (typeof v === 'number') metricValues[k] = v
        })
      }
    }

    const numericList = Object.values(metricValues)
    const minVal = numericList.length > 0 ? Math.min(...numericList) : 0
    const maxVal = numericList.length > 0 ? Math.max(...numericList) : 1
    const span = maxVal > minVal ? maxVal - minVal : 1

    graph.batch(() => {
      graph.nodes().forEach((node) => {
        // Normalização de tamanho
        let normSize: number
        if (sizeBy === 'uniforme') {
          normSize = 0.5
        } else if (metricValues[node.id()] !== undefined) {
          normSize = 0.1 + ((metricValues[node.id()] - minVal) / span) * 0.9
        } else {
          const rawDegree = Number(node.data('size_metric') ?? 0.5)
          normSize = Math.max(0.1, Math.min(1.0, rawDegree))
        }
        node.data('size_metric', normSize)

        // 2. Reagir à cor (colorBy)
        if (colorBy === 'comunidade') {
          const commVals = metrics?.['graph.community']?.values as Record<string, string> | undefined
          const commData = (commVals?.[node.id()] ?? node.data('community')) as string | undefined
          if (commData && commData.startsWith('C')) {
            const idx = parseInt(commData.replace('C', ''), 10) - 1
            const color = communityColors[idx % communityColors.length]
            node.style({
              'underlay-color': color,
              'underlay-opacity': 0.45,
              'underlay-padding': '6px',
              'border-width': 0,
            })
          } else {
            node.style({ 'underlay-opacity': 0, 'border-width': 0 })
          }
        } else if (colorBy === 'risco') {
          const riskVals = metrics?.['flow.bottleneck_risk']?.values as
            | Record<string, { level?: string }>
            | undefined
          const bRisk = riskVals?.[node.id()]
          const isoVals = metrics?.['team.isolation']?.values as
            | Record<string, { flag?: boolean }>
            | undefined
          const iso = isoVals?.[node.id()]
          const isRisk =
            bRisk?.level === 'high' || iso?.flag === true || node.data('blocked') === true

          if (isRisk) {
            node.style({
              'underlay-color': '#ef4444',
              'underlay-opacity': 0.5,
              'underlay-padding': '6px',
              'border-width': '2px',
              'border-style': 'dashed',
              'border-color': '#ef4444',
            })
          } else {
            node.style({ 'underlay-opacity': 0, 'border-width': 0 })
          }
        } else if (colorBy === 'categoria da tarefa') {
          if (node.data('type') === 'task') {
            const st = node.data('status_category')
            let taskColor = '#64748b'
            if (st === 'done') taskColor = '#10b981'
            else if (st === 'doing') taskColor = '#3b82f6'
            else if (st === 'review') taskColor = '#8b5cf6'
            node.style({
              'underlay-color': taskColor,
              'underlay-opacity': 0.5,
              'underlay-padding': '5px',
              'border-width': 0,
            })
          } else {
            node.style({ 'underlay-opacity': 0, 'border-width': 0 })
          }
        } else {
          // colorBy === 'tipo' (padrão)
          node.style({ 'underlay-opacity': 0, 'border-width': 0 })
        }
      })
      syncNodeSizesWithZoom(graph)
    })
  }, [sizeBy, colorBy, metrics])

  // 3. Reagir a highlightIds (destaque de signals)
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    graph.batch(() => {
      graph.elements().removeClass('signal-highlighted faded-by-signal')
      if (highlightIds && highlightIds.length > 0) {
        const targetNodes = graph.nodes().filter((node) => highlightIds.includes(node.id()))
        if (targetNodes.length > 0) {
          graph.elements().addClass('faded-by-signal')
          targetNodes.removeClass('faded-by-signal').addClass('signal-highlighted')
          targetNodes.connectedEdges().forEach((edge) => {
            if (highlightIds.includes(edge.source().id()) && highlightIds.includes(edge.target().id())) {
              edge.removeClass('faded-by-signal').addClass('signal-highlighted')
            }
          })
          graph.animate({
            fit: {
              eles: targetNodes,
              padding: 60,
            },
            duration: 400,
          })
        }
      }
    })
  }, [highlightIds])


  return (
    <div
      className={styles.graphCanvas}
      ref={containerRef}
      role="application"
      tabIndex={0}
      aria-label="Grafo de colaboração interativo. Navegue com o cursor ou utilize os atalhos de teclado."
    />
  )
}

export default GraphCanvas
