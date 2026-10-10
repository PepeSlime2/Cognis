import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'

function TrelloCallback() {
  const [searchParams] = useSearchParams()
  const code = searchParams.get('code')
  const state = searchParams.get('state')
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

  if (!code || !state) {
    return (
      <main>
        <h1>Não foi possível conectar o Trello</h1>
        <p>A autorização não retornou os dados necessários. Inicie a conexão novamente.</p>
        <Link to="/">Voltar ao início</Link>
      </main>
    )
  }

  if (exchangeQuery.isPending) {
    return <main><h1>Conectando ao Trello...</h1></main>
  }

  if (exchangeQuery.isError) {
    return (
      <main>
        <h1>Falha ao conectar o Trello</h1>
        <p role="alert">{exchangeQuery.error.message}</p>
        <Link to="/">Voltar ao início</Link>
      </main>
    )
  }

  return (
    <main>
      <h1>Trello conectado</h1>
      <p>Conta conectada: {exchangeQuery.data.username}</p>
      <Link to="/">Voltar ao início</Link>
    </main>
  )
}

export default TrelloCallback
