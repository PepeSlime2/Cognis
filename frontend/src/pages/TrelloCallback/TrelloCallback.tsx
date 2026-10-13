import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'

const containerStyle: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '24px',
  backgroundColor: '#02001b',
  backgroundImage: 'radial-gradient(circle at 50% 50%, rgba(13, 10, 48, 0.9) 0%, #02001b 100%)',
  color: '#f8fafc',
}

const cardStyle: React.CSSProperties = {
  maxWidth: '440px',
  width: '100%',
  padding: '36px',
  borderRadius: '16px',
  background: 'rgba(10, 11, 40, 0.75)',
  backdropFilter: 'blur(14px)',
  border: '1px solid rgba(139, 92, 246, 0.25)',
  boxShadow: '0 16px 40px -8px rgba(0, 0, 0, 0.65)',
  display: 'flex',
  flexDirection: 'column',
  gap: '14px',
  textAlign: 'center',
  alignItems: 'center',
}

const linkStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  marginTop: '8px',
  padding: '10px 20px',
  borderRadius: '10px',
  background: 'linear-gradient(135deg, #7c3aed 0%, #06b6d4 100%)',
  color: '#ffffff',
  fontSize: '13px',
  fontWeight: 600,
  textDecoration: 'none',
  boxShadow: '0 4px 15px rgba(124, 58, 237, 0.35)',
}

function TrelloCallback() {
  const [searchParams] = useSearchParams()
  const hashParams = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.hash.replace(/^#\/?/, ''))
    : new URLSearchParams()

  const code = searchParams.get('code') || hashParams.get('code')
  const state = searchParams.get('state') || hashParams.get('state')
  const oauthError = searchParams.get('error') || hashParams.get('error')
  const oauthErrorDescription = searchParams.get('error_description') || hashParams.get('error_description')

  const exchangeQuery = useQuery({
    queryKey: ['auth', 'trello-exchange', code, state],
    queryFn: () => {
      if (!code || !state) {
        throw new Error('A autorização não retornou os dados necessários.')
      }
      const params = new URLSearchParams({ code, state })
      return api.get<{ connected: string; username: string }>(
        `/auth/trello/exchange?${params}`,
      )
    },
    enabled: Boolean(code && state),
    retry: false,
  })

  if (oauthError) {
    return (
      <main style={containerStyle}>
        <div style={cardStyle}>
          <h2 style={{ margin: 0, fontSize: '20px' }}>Erro na autorização do Trello</h2>
          <p style={{ margin: 0, color: '#fca5a5', fontSize: '14px' }}>
            {oauthErrorDescription || oauthError}
          </p>
          <span style={{ fontSize: '12px', color: '#94a3b8' }}>
            Código: {oauthError}
          </span>
          <Link to="/" style={linkStyle}>Voltar ao início</Link>
        </div>
      </main>
    )
  }

  if (!code || !state) {
    const rawParams = searchParams.toString()
    return (
      <main style={containerStyle}>
        <div style={cardStyle}>
          <h2 style={{ margin: 0, fontSize: '20px' }}>Não foi possível conectar o Trello</h2>
          <p style={{ margin: 0, color: '#fca5a5', fontSize: '14px' }}>
            A autorização não retornou os dados necessários. Inicie a conexão novamente.
          </p>
          {rawParams ? (
            <p style={{ margin: 0, color: '#94a3b8', fontSize: '12px', wordBreak: 'break-all' }}>
              Parâmetros recebidos: {rawParams}
            </p>
          ) : null}
          <Link to="/" style={linkStyle}>Voltar ao início</Link>
        </div>
      </main>
    )
  }

  if (exchangeQuery.isPending) {
    return (
      <main style={containerStyle}>
        <div style={cardStyle}>
          <h2 style={{ margin: 0, fontSize: '20px' }}>Conectando ao Trello...</h2>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '14px' }}>
            Validando suas credenciais de acesso seguro.
          </p>
        </div>
      </main>
    )
  }

  if (exchangeQuery.isError) {
    return (
      <main style={containerStyle}>
        <div style={cardStyle}>
          <h2 style={{ margin: 0, fontSize: '20px' }}>Falha ao conectar o Trello</h2>
          <p style={{ margin: 0, color: '#fca5a5', fontSize: '14px' }} role="alert">
            {exchangeQuery.error.message}
          </p>
          <Link to="/" style={linkStyle}>Voltar ao início</Link>
        </div>
      </main>
    )
  }

  return (
    <main style={containerStyle}>
      <div style={cardStyle}>
        <h2 style={{ margin: 0, fontSize: '20px' }}>Trello Conectado</h2>
        <p style={{ margin: 0, color: '#86efac', fontSize: '14px' }}>
          Conta conectada: <strong>{exchangeQuery.data.username}</strong>
        </p>
        <Link to="/" style={linkStyle}>Voltar ao início</Link>
      </div>
    </main>
  )
}

export default TrelloCallback
