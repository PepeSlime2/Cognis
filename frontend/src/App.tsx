import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import './App.css'
import { ApiError, api, sessionQueryKey } from './api/client'
import type { SessionResponse } from './api/client'
import Auth from './components/Auth/Auth'
import Home from './pages/Home/Home'
import SettingsPage from './pages/Settings/SettingsPage'
import TrelloCallback from './pages/TrelloCallback/TrelloCallback'
import { MetricsPage } from './pages/Metrics/MetricsPage'
import { PeoplePage } from './pages/People/PeoplePage'

function SessionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [logoutError, setLogoutError] = useState('')
  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => api.get<SessionResponse>('/auth/me'),
  })

  if (sessionQuery.isPending) {
    return (
      <main style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#02001b', color: '#94a3b8' }}>
        <p>Carregando sessão...</p>
      </main>
    )
  }

  if (sessionQuery.isError && !(sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401)) {
    return (
      <main style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#02001b', color: '#f8fafc', gap: 14 }}>
        <h2>Não foi possível carregar sua sessão</h2>
        <p style={{ color: '#fca5a5' }}>{sessionQuery.error.message}</p>
        <button
          onClick={() => void sessionQuery.refetch()}
          type="button"
          style={{ padding: '10px 18px', borderRadius: 8, border: '1px solid rgba(139,92,246,0.3)', background: 'rgba(28,20,80,0.6)', color: '#fff', cursor: 'pointer' }}
        >
          Tentar novamente
        </button>
      </main>
    )
  }

  if (sessionQuery.isError) {
    return (
      <Auth
        onAuthenticated={(session) => {
          queryClient.setQueryData(sessionQueryKey, session)
          setLogoutError('')
          navigate('/')
        }}
      />
    )
  }

  const session = sessionQuery.data
  if (!session) {
    return <main><h1>Não foi possível carregar sua sessão</h1></main>
  }

  const logout = async () => {
    setLogoutError('')
    try {
      await api.post('/auth/logout')
      await queryClient.invalidateQueries({ queryKey: sessionQueryKey })
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Não foi possível sair.')
    }
  }

  return (
    <>
      {logoutError && <p role="alert">{logoutError}</p>}
      <Home onLogout={logout} connections={session.connections} projectId={projectId} />
    </>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/trello-callback" element={<TrelloCallback />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/p/:projectId/metrics" element={<MetricsPage />} />
      <Route path="/p/:projectId/people" element={<PeoplePage />} />
      <Route path="/p/:projectId" element={<SessionPage />} />
      <Route path="/login" element={<SessionPage />} />
      <Route path="/" element={<SessionPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
