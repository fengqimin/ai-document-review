import { Button, Input, makeStyles, Card, CardHeader, Text, tokens } from '@fluentui/react-components'
import { Person20Regular, LockClosed20Regular } from '@fluentui/react-icons'
import { FormEvent, useState } from 'react'
import { login } from '../../auth'

const useStyles = makeStyles({
  wrapper: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: '60vh'
  },
  card: { width: '360px', maxWidth: '90vw', padding: '8px' },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '16px'
  },
  error: { color: tokens.colorPaletteRedForeground1, fontSize: '13px' }
})

function Login({ onLogin }: { onLogin: (user: { name: string; username: string }) => void }) {
  const classes = useStyles()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string>()
  const [inProgress, setInProgress] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    setInProgress(true)
    try {
      const user = await login(username, password)
      onLogin(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed. Please try again.')
    } finally {
      setInProgress(false)
    }
  }

  return (
    <div className={classes.wrapper}>
      <Card className={classes.card}>
        <CardHeader
          header={<Text size={500} weight="semibold">Sign in</Text>}
          description={<Text size={300}>Use your local AI Document Review account</Text>}
        />
        <form className={classes.form} onSubmit={handleSubmit}>
          <Input
            content={<Person20Regular />}
            placeholder="Username"
            value={username}
            onChange={(_, data) => setUsername(data.value)}
            required
            aria-label="Username"
          />
          <Input
            content={<LockClosed20Regular />}
            type="password"
            placeholder="Password"
            value={password}
            onChange={(_, data) => setPassword(data.value)}
            required
            aria-label="Password"
          />
          {error && <div className={classes.error}>{error}</div>}
          <Button appearance="primary" size="large" type="submit" disabled={inProgress}>
            {inProgress ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  )
}

export default Login
