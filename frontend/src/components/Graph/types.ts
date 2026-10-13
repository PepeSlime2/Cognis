import type { GraphLayer, GraphNodeData } from '../../api/client'

export type DockState = {
  leftOpen: boolean
  rightOpen: boolean
  rightTab: 'details' | 'insights'
  focusMode: boolean
  leftSection: string
}

export type GraphSelection =
  | { kind: 'node'; id: string; data: GraphNodeData }
  | { kind: 'edge'; id: string; data: Record<string, unknown> }
  | null

export type GraphViewState = {
  window: string
  layer: GraphLayer
  includeBots: boolean
  sizeBy: string
  colorBy: string
  layout: string
  fxLevel: 'full' | 'lite' | 'off'
  minWeight: number
  showLabels: boolean
  query: string
  pathMode: boolean
  selection: GraphSelection
  highlightIds: string[]
}
