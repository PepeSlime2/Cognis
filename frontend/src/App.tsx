import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import './App.css'
import { ApiError, api, sessionQueryKey } from './api/client'
import type { SessionResponse } from './api/client'
import Auth from './components/Auth/Auth'
import Home from './pages/Home/Home'
import TrelloCallback from './pages/TrelloCallback/TrelloCallback'

function SessionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState('')
  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => api.get<SessionResponse>('/auth/me'),
  })

  if (sessionQuery.isPending) {
    return <main><h1>Carregando...</h1></main>
  }

  if (sessionQuery.isError && !(sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401)) {
    return (
      <main>
        <h1>Não foi possível carregar sua sessão</h1>
        <p>{sessionQuery.error.message}</p>
        <button onClick={() => void sessionQuery.refetch()} type="button">Tentar novamente</button>
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
      <Home onLogout={logout} connections={session.connections} />
    </>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/trello-callback" element={<TrelloCallback />} />
      <Route path="/login" element={<SessionPage />} />
      <Route path="/" element={<SessionPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
