import { Avatar, Button, Spinner, makeStyles } from '@fluentui/react-components'
import { ChevronLeft20Regular, ArrowExit20Regular } from '@fluentui/react-icons'
import { useEffect, useState } from 'react'
import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import logo from './assets/ai-doc.png'
import { AuthUser, clearSession, fetchAuthDisabled, fetchCurrentUser, logout } from './auth'
import Files from './pages/files/Files'
import Login from './pages/login/Login'
import Review from './pages/review/Review'

const useStyles = makeStyles({
  app: { backgroundColor: '#f5f5f5', color: '#fff', minHeight: '100vh' },
  header: { display: 'flex', flexDirection: 'row', justifyContent: 'space-between', padding: '8px' },
  logo: {
    display: 'flex',
    alignItems: 'center',
    marginLeft: '20px',
    '& img': {
      height: '25px',
      padding: '5px',
      marginLeft: '10px'
    },
    '& h3': {
      color: '#000'
    }
  },
  user: { display: 'flex', alignItems: 'center', gap: '8px', marginRight: '12px' },
  userName: { color: '#000' },
  main: { display: 'flex', flexDirection: 'column', alignItems: 'center' },
  center: { display: 'flex', justifyContent: 'center', paddingTop: '120px' }
})

type AuthState =
  | { kind: 'loading' }
  | { kind: 'login' }
  | { kind: 'ready'; authDisabled: boolean; user: AuthUser | null }

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const classes = useStyles()
  const [authState, setAuthState] = useState<AuthState>({ kind: 'loading' })

  // Resolve auth once on startup: honor AUTH_DISABLED, validate any stored JWT.
  useEffect(() => {
    let cancelled = false
    async function resolve() {
      const authDisabled = await fetchAuthDisabled()
      if (cancelled) return
      if (authDisabled) {
        setAuthState({ kind: 'ready', authDisabled: true, user: null })
        return
      }
      const user = await fetchCurrentUser()
      if (cancelled) return
      if (user) {
        setAuthState({ kind: 'ready', authDisabled: false, user })
      } else {
        setAuthState({ kind: 'login' })
      }
    }
    resolve()
    return () => {
      cancelled = true
    }
  }, [])

  const handleLogin = (user: AuthUser) => {
    setAuthState({ kind: 'ready', authDisabled: false, user })
  }

  const handleLogout = async () => {
    await logout()
    setAuthState({ kind: 'login' })
  }

  if (authState.kind === 'loading') {
    return (
      <div className={classes.app}>
        <div className={classes.center}>
          <Spinner label="Loading..." />
        </div>
      </div>
    )
  }

  if (authState.kind === 'login') {
    return (
      <div className={classes.app}>
        <header className={classes.header}>
          <div className={classes.logo}>
            <img src={logo} alt="logo" />
            <h3>AI Document Review</h3>
          </div>
        </header>
        <main className={classes.main}>
          <Login onLogin={handleLogin} />
        </main>
      </div>
    )
  }

  const { user } = authState

  return (
    <div className={classes.app}>
      <header className={classes.header}>
        <div className={classes.logo}>
          {location.key !== 'default' && (
            <Button size="large" shape="circular" icon={<ChevronLeft20Regular />} onClick={() => navigate(-1)} />
          )}
          <img src={logo} alt="logo" />
          <h3>AI Document Review</h3>
        </div>
        <div className={classes.user}>
          {user && <span className={classes.userName}>{user.name || user.username}</span>}
          <Avatar aria-label="User" name={user?.name || user?.username || 'User'} size={40} />
          {!authState.authDisabled && (
            <Button
              appearance="transparent"
              icon={<ArrowExit20Regular />}
              aria-label="Log out"
              title="Log out"
              onClick={handleLogout}
            />
          )}
        </div>
      </header>

      <main className={classes.main}>
        <Routes>
          <Route path="/" element={<Files />} />
          <Route path="/review" element={<Review />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
