import './App.css'
import Home from "./pages/Home/Home"
import { useEffect, useState } from 'react'
import Auth from './components/Auth/Auth'

const API_URL = '/api'

function App() {
  const [trelloStatus, setTrelloStatus] = useState<'loading' | 'success' | 'error'>('loading')
    const [authenticated, setAuthenticated] = useState<boolean | null>(null)

  useEffect(() => {
    if (window.location.pathname !== '/trello-callback') return

    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const state = params.get('state')
    if (!code || !state) {
      setTrelloStatus('error')
      return
    }

    fetch(`${API_URL}/auth/trello/exchange?${new URLSearchParams({ code, state })}`, {
      credentials: 'include',
    })
      .then((response) => {
        if (!response.ok) throw new Error('Trello OAuth falhou')
        return response.json()
      })
      .then(() => setTrelloStatus('success'))
      .catch(() => setTrelloStatus('error'))
  }, [])

    useEffect(() => {
      if (window.location.pathname === '/trello-callback') return
      fetch('/api/auth/me', { credentials: 'include' })
        .then((response) => setAuthenticated(response.ok))
        .catch(() => setAuthenticated(false))
    }, [])

  if (window.location.pathname === '/trello-callback') {
    return <main><h1>{trelloStatus === 'success' ? 'Trello conectado' : trelloStatus === 'error' ? 'Falha ao conectar o Trello' : 'Conectando ao Trello...'}</h1></main>
  }

    if (authenticated === null) return <main><h1>Carregando...</h1></main>
    if (!authenticated) return <Auth onAuthenticated={() => setAuthenticated(true)} />

  return (
      <Home onLogout={() => {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
          .finally(() => setAuthenticated(false))
      }} />
  )
}

export default App
