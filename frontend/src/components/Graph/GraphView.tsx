import GraphShell from './GraphShell'

const GraphView = ({ projectId }: { projectId: string }) => {
  return <GraphShell projectId={projectId} onLogout={() => {}} />
}

export default GraphView
