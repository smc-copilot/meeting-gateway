import type { Row } from './types'

const base = String(import.meta.env.VITE_MEETING_GATEWAY_URL || '/meeting-gateway').replace(/\/$/, '')
const clientId = String(import.meta.env.VITE_MEETING_CLIENT_ID || '')
const clientSecret = String(import.meta.env.VITE_MEETING_CLIENT_SECRET || '')
const returnTo = String(import.meta.env.VITE_MEETING_OAUTH_RETURN_TO || (typeof window !== 'undefined' ? window.location.origin + '/meeting/connections' : ''))

let access: { value: string; expires: number; connectionId: string } | null = null
let gatewaySession: { token: string; expires: number } | null = null

export class GatewayError extends Error {
  constructor(public reason: string, public trace: string, public status: number, message: string) { super(message) }
}

export function hasGatewaySession(): boolean {
  return (!!access && access.expires > Date.now()) || (!!gatewaySession && gatewaySession.expires > Date.now())
}

export function clearGatewaySession() {
  access = null
  gatewaySession = null
}

function clientHeaders(): Record<string, string> {
  if (!clientId || !clientSecret) {
    throw new GatewayError('TOKEN_INVALID', '', 401, 'Configure VITE_MEETING_CLIENT_ID and VITE_MEETING_CLIENT_SECRET')
  }
  return { Authorization: 'Basic ' + btoa(`${clientId}:${clientSecret}`), 'Content-Type': 'application/json' }
}

async function parse(response: Response): Promise<any> {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new GatewayError(data.reason || 'HTTP_ERROR', data.trace_id || '', response.status, data.message || response.statusText)
  return data.data === undefined ? data : data.data
}

export async function startAuthorize(applicationId = '') {
  const response = await fetch(base + '/api/v1/oauth/authorizations', {
    method: 'POST', credentials: 'omit', headers: clientHeaders(),
    body: JSON.stringify({ application_id: applicationId, return_to: returnTo }),
  })
  return parse(response)
}

export async function exchangeAuthorizationCode(authorizationCode: string) {
  const response = await fetch(base + '/api/v1/oauth/sessions', {
    method: 'POST', credentials: 'omit', headers: clientHeaders(),
    body: JSON.stringify({ authorization_code: authorizationCode }),
  })
  const data = await parse(response)
  access = {
    value: data.access_token,
    expires: Date.now() + data.expires_in * 1000,
    connectionId: data.connection_id || '',
  }
  if (data.session_token) {
    gatewaySession = {
      token: data.session_token,
      expires: Date.now() + (data.session_expires_in || data.expires_in) * 1000,
    }
  }
  return data
}

export async function consumeOAuthReturn(search: string) {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const code = params.get('authorization_code')
  if (!code) return null
  return exchangeAuthorizationCode(code)
}

function sessionToken(): string {
  if (!gatewaySession || gatewaySession.expires <= Date.now()) {
    clearGatewaySession()
    throw new GatewayError('IDENTITY_REAUTH_REQUIRED', '', 401, 'Authorize with Tencent Meeting again')
  }
  return gatewaySession.token
}

async function businessToken(): Promise<string> {
  if (access && access.expires > Date.now() + 15000) return access.value
  if (!gatewaySession || gatewaySession.expires <= Date.now()) {
    clearGatewaySession()
    throw new GatewayError('UPSTREAM_REAUTH_REQUIRED', '', 401, 'Authorize with Tencent Meeting again')
  }
  const response = await fetch(base + '/api/v1/portal/session', {
    method: 'POST', credentials: 'omit', headers: { Authorization: 'Bearer ' + sessionToken() },
  })
  const data = await parse(response)
  access = { value: data.access_token, expires: Date.now() + data.expires_in * 1000, connectionId: access?.connectionId || '' }
  return access.value
}

export async function api(path: string, options: { method?: string; body?: unknown; business?: boolean; idempotencyKey?: string } = {}): Promise<any> {
  if (!path.startsWith('/api/v1/')) throw new Error('Invalid gateway route')
  const credential = options.business ? await businessToken() : sessionToken()
  const headers: Record<string, string> = { Authorization: 'Bearer ' + credential }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey
  const response = await fetch(base + path, {
    method: options.method || 'GET', credentials: 'omit', headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  return parse(response)
}

export async function downloadAsset(asset: Row, purpose: string) {
  const picker = (window as any).showSaveFilePicker
  if (!picker) throw new GatewayError('FILE_SYSTEM_API_REQUIRED', '', 400, 'Large downloads require File System Access API')
  const handle = await picker({ suggestedName: 'meeting-' + String(asset.id) })
  const ticket = await api('/api/v1/assets/' + encodeURIComponent(asset.id) + '/download-tickets', { method: 'POST', business: true, body: { purpose } })
  const response = await fetch(base + ticket.download_path, { credentials: 'omit', headers: { Authorization: 'Bearer ' + await businessToken() } })
  if (!response.ok) { await parse(response); return }
  if (!response.body) throw new Error('Streaming response required')
  const sink = await handle.createWritable()
  try { await response.body.pipeTo(sink) } catch (error) { try { await sink.abort() } catch {} throw error }
}

export function errorText(error: unknown): string {
  if (error instanceof GatewayError) return `${error.message} [${error.reason}] ${error.trace}`
  return error instanceof Error ? error.message : String(error)
}
