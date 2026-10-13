import { useEffect, useMemo, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, LayoutOptions, StylesheetJson } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import type { GraphNodeData, ProjectGraph } from '../../api/client'
import styles from './graph.module.css'

cytoscape.use(fcose)

const graphStyle: StylesheetJson = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      color: '#f1f3ff',
      'font-size': '11px',
      'font-weight': 600,
      'text-wrap': 'ellipsis',
      'text-max-width': '110px',
      'text-valign': 'bottom',
      'text-margin-y': 8,
      width: 'mapData(size_metric, 0, 1, 34, 62)',
      height: 'mapData(size_metric, 0, 1, 34, 62)',
      'background-color': '#6248c7',
      'border-width': 2,
      'border-color': '#b9a5ff',
      'overlay-opacity': 0,
    },
  },
  {
    selector: 'node[type = "person"]',
    style: { 'background-color': '#117caa', 'border-color': '#73ddff' },
  },
  {
    selector: 'node[type = "task"]',
    style: { 'background-color': '#6742c1', 'border-color': '#c6aaff' },
  },
  {
    selector: 'node[type = "pr"]',
    style: { 'background-color': '#315ab3', 'border-color': '#95b8ff' },
  },
  {
    selector: 'node[type = "commit"]',
    style: { 'background-color': '#3d466b', 'border-color': '#9da9dc' },
  },
  {
    selector: 'node[type = "repo"]',
    style: { 'background-color': '#087c75', 'border-color': '#6be3d5' },
  },
  {
    selector: 'node[type = "module"]',
    style: { 'background-color': '#527b37', 'border-color': '#b9ec80' },
  },
  {
    selector: 'node[type = "column"]',
    style: { 'background-color': '#785628', 'border-color': '#f2c77d' },
  },
  {
    selector: 'node:selected',
    style: { 'border-width': 4, 'border-color': '#ffffff' },
  },
  {
    selector: 'edge',
    style: {
      width: 'mapData(weight, 1, 8, 1, 4)',
      'line-color': '#64719b',
      'target-arrow-color': '#8795c2',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      opacity: 0.7,
      label: 'data(type)',
      color: '#c3cae8',
      'font-size': '8px',
      'text-rotation': 'autorotate',
      'text-background-color': '#080721',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge[type = "review"]',
    style: { 'line-color': '#ffbf69', 'target-arrow-color': '#ffbf69' },
  },
  {
    selector: 'edge[type = "comment"]',
    style: { 'line-color': '#66d5cb', 'target-arrow-color': '#66d5cb' },
  },
]

type GraphCanvasProps = {
  elements: ProjectGraph['elements']
  labelsVisible: boolean
  onNodeSelect: (node: GraphNodeData | null) => void
  onGraphReady: (graph: Core | null) => void
}

const layoutOptions: LayoutOptions = {
  name: 'fcose',
  quality: 'default',
  animate: true,
  animationDuration: 500,
  randomize: true,
  fit: true,
  padding: 44,
  nodeRepulsion: 4500,
  idealEdgeLength: 120,
  numIter: 2500,
}

const GraphCanvas = ({
  elements,
  labelsVisible,
  onNodeSelect,
  onGraphReady,
}: GraphCanvasProps) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Core | null>(null)
  const onNodeSelectRef = useRef(onNodeSelect)
  const graphElements = useMemo(
    () => [...elements.nodes, ...elements.edges] as ElementDefinition[],
    [elements.edges, elements.nodes],
  )

  useEffect(() => {
    onNodeSelectRef.current = onNodeSelect
  }, [onNodeSelect])

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
      onNodeSelectRef.current(event.target.data() as GraphNodeData)
    })
    graph.on('tap', (event) => {
      if (event.target === graph) onNodeSelectRef.current(null)
    })
    onGraphReady(graph)

    return () => {
      onNodeSelectRef.current(null)
      graphRef.current = null
      onGraphReady(null)
      graph.destroy()
    }
  }, [onGraphReady])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return

    graph.batch(() => {
      graph.elements().remove()
      graph.add(graphElements)
    })
    graph.nodes().style('label', labelsVisible ? 'data(label)' : '')
    if (graphElements.length > 0) graph.layout(layoutOptions).run()
  }, [graphElements, labelsVisible])

  return <div className={styles.graphCanvas} ref={containerRef} role="img" aria-label="Grafo do projeto" />
}

export default GraphCanvas
