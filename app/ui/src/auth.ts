/** Local JWT auth helpers (replaces MSAL). Tokens live in sessionStorage so
 * they vanish when the tab closes — a smaller XSS exposure than the previous
 * localStorage MSAL cache. */

const TOKEN_KEY = 'adr.access_token'
const USER_KEY = 'adr.user'

export interface AuthUser {
  oid: string
  name: string
  username: string
}

interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): AuthUser | null {
  const raw = sessionStorage.getItem(USER_KEY)
  return raw ? (JSON.parse(raw) as AuthUser) : null
}

function storeSession(token: string, user: AuthUser): void {
  sessionStorage.setItem(TOKEN_KEY, token)
  sessionStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(USER_KEY)
}

export function isLoggedIn(): boolean {
  return Boolean(getAccessToken())
}

async function requestJson(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `API error (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      else if (body?.message) message = body.message
    } catch {
      /* keep default message */
    }
    throw new Error(message)
  }
  return response
}

/** True when the backend runs with AUTH_DISABLED=true (no login required). */
export async function fetchAuthDisabled(): Promise<boolean> {
  const response = await fetch('/api/v1/auth/config')
  if (!response.ok) return false
  const body = await response.json()
  return Boolean(body?.auth_disabled)
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const response = await requestJson('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  const body = (await response.json()) as LoginResponse
  storeSession(body.access_token, body.user)
  return body.user
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getAccessToken()
  if (!token) return null
  try {
    const response = await requestJson('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` }
    })
    return (await response.json()) as AuthUser
  } catch {
    // Invalid/expired token: discard it and force a fresh login.
    clearSession()
    return null
  }
}

export async function logout(): Promise<void> {
  const token = getAccessToken()
  if (token) {
    try {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      })
    } catch {
      /* stateless JWT: client-side discard is always enough */
    }
  }
  clearSession()
}
