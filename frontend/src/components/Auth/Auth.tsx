import { useState } from 'react'
import type { FormEvent } from 'react'
import styles from './auth.module.css'

type AuthProps = {
  onAuthenticated: () => void
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
      const response = await fetch(`/api/auth/${mode}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name: mode === 'register' ? name : undefined }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'Não foi possível continuar')
      onAuthenticated()
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
