import type { EdgeSingular, NodeSingular } from 'cytoscape'

declare module 'cytoscape' {
  interface BaseLayoutOptions {
    quality?: 'draft' | 'default' | 'proof'
    animate?: boolean | 'end'
    animationDuration?: number
    randomize?: boolean
    fit?: boolean
    padding?: number
    nodeRepulsion?: number | ((node: NodeSingular) => number)
    idealEdgeLength?: number | ((edge: EdgeSingular) => number)
    numIter?: number
  }
}
