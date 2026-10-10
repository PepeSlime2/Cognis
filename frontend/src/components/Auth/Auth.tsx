import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { SessionResponse } from '../../api/client'
import styles from './auth.module.css'

type AuthProps = {
  onAuthenticated: (session: SessionResponse) => void
}

const Auth = ({ onAuthenticated }: AuthProps) => {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.post<{ user_id: string }>(`/auth/${mode}`, {
        email,
        password,
        name: mode === 'register' ? name : undefined,
      })
      const session = await api.get<SessionResponse>('/auth/me')
      onAuthenticated(session)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Não foi possível continuar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.panel}>
        <p className={styles.eyebrow}>COGNIS</p>
        <h1>{mode === 'login' ? 'Entrar no sistema' : 'Criar sua conta'}</h1>
        <p className={styles.description}>Acompanhe suas fontes de trabalho em um só lugar.</p>
        <form onSubmit={submit}>
          {mode === 'register' && (
            <label>
              Nome
              <input value={name} onChange={(event) => setName(event.target.value)} required />
            </label>
          )}
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            Senha
            <input type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {error && <p className={styles.error}>{error}</p>}
          <button disabled={loading} type="submit">
            {loading ? 'Aguarde...' : mode === 'login' ? 'Entrar' : 'Cadastrar'}
          </button>
        </form>
        <button className={styles.switch} onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }} type="button">
          {mode === 'login' ? 'Ainda não tenho uma conta' : 'Já tenho uma conta'}
        </button>
      </section>
    </main>
  )
}

export default Auth
