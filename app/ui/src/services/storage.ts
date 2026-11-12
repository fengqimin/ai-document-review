/** Document store access via the local API (replaces direct browser-to-Blob
 * access with the authenticated /api/v1/documents endpoints). */

import { getAccessToken } from '../auth'
import { DocumentInfo } from '../types/document'

const documentsBaseUrl = '/api/v1/documents/'

function authHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function check(response: Response): Promise<Response> {
  if (!response.ok) {
    let message = `Document API error (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      else if (body?.message) message = body.message
    } catch {
      /* keep default */
    }
    throw new Error(message)
  }
  return response
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const response = await check(await fetch(documentsBaseUrl, { headers: authHeaders() }))
  return (await response.json()) as DocumentInfo[]
}

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData()
  form.append('file', file, file.name)
  const response = await check(
    await fetch(documentsBaseUrl, { method: 'POST', headers: authHeaders(), body: form })
  )
  return (await response.json()) as DocumentInfo
}

export async function getDocument(name: string): Promise<Blob> {
  const response = await check(
    await fetch(`${documentsBaseUrl}${encodeURIComponent(name)}/file`, { headers: authHeaders() })
  )
  return await response.blob()
}

export async function deleteDocument(name: string): Promise<void> {
  await check(
    await fetch(`${documentsBaseUrl}${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: authHeaders()
    })
  )
}
