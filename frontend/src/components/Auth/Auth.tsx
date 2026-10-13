import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { SessionResponse } from '../../api/client'
import cognisLogo from '../../assets/CognisLogotipo.png'
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
        <div className={styles.brandHeader}>
          <img src={cognisLogo} alt="Cognis" className={styles.logoImg} />
          <p className={styles.subtitle}>Análise inteligente de projetos por grafos</p>
        </div>

        <div className={styles.tabNav} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={`${styles.tabButton} ${mode === 'login' ? styles.tabActive : ''}`}
            onClick={() => {
              setMode('login')
              setError('')
            }}
          >
            Entrar
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={`${styles.tabButton} ${mode === 'register' ? styles.tabActive : ''}`}
            onClick={() => {
              setMode('register')
              setError('')
            }}
          >
            Cadastrar
          </button>
        </div>

        <h1 className={styles.title}>
          {mode === 'login' ? 'Entrar no Sistema' : 'Criar Nova Conta'}
        </h1>
        <p className={styles.description}>
          {mode === 'login'
            ? 'Acesse a visualização de relacionamentos, tarefas e colaboração da sua equipe.'
            : 'Comece a mapear fluxos de trabalho e métricas de colaboração em tempo real.'}
        </p>

        <form onSubmit={submit} className={styles.form}>
          {mode === 'register' && (
            <label className={styles.fieldLabel}>
              <span>Nome Completo</span>
              <input
                className={styles.input}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Seu nome"
                required
              />
            </label>
          )}

          <label className={styles.fieldLabel}>
            <span>Endereço de Email</span>
            <input
              className={styles.input}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="seu.email@exemplo.com"
              required
            />
          </label>

          <label className={styles.fieldLabel}>
            <span>Senha</span>
            <input
              className={styles.input}
              type="password"
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Mínimo de 8 caracteres"
              required
            />
          </label>

          {error && <p className={styles.error} role="alert">{error}</p>}

          <button disabled={loading} type="submit" className={styles.submitBtn}>
            {loading ? 'Processando…' : mode === 'login' ? 'Acessar Cognis' : 'Finalizar Cadastro'}
          </button>
        </form>

        <button
          className={styles.switch}
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError('')
          }}
          type="button"
        >
          {mode === 'login'
            ? 'Ainda não tem uma conta? Cadastre-se'
            : 'Já possui uma conta registrada? Fazer login'}
        </button>
      </section>
    </main>
  )
}

export default Auth
