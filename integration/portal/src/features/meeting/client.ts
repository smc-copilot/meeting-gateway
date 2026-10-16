import { useAuthStore } from '@/stores/auth'
import type { Row, Page } from './types'

const base = String(import.meta.env.VITE_MEETING_GATEWAY_URL || '/meeting-gateway').replace(/\/$/, '')
let access: { value: string; expires: number; backend: string } | null = null
export class GatewayError extends Error {
  constructor(public reason: string, public trace: string, public status: number, message: string) { super(message) }
}
function backendToken(): string {
  const value = useAuthStore().token
  if (!value) { access = null; throw new GatewayError('TOKEN_INVALID', '', 401, 'Authentication required') }
  return value
}
async function parse(response: Response): Promise<any> {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new GatewayError(data.reason || 'HTTP_ERROR', data.trace_id || '', response.status, data.message || response.statusText)
  return data.data === undefined ? data : data.data
}
async function token(): Promise<string> {
  const backend = backendToken()
  if (access && access.backend === backend && access.expires > Date.now() + 15000) return access.value
  const response = await fetch(base + '/api/v1/portal/session', { method:'POST', credentials:'omit', headers:{Authorization:'Bearer ' + backend} })
  const data = await parse(response)
  access = { value:data.access_token, expires:Date.now() + data.expires_in * 1000, backend }
  return access.value
}
export async function api(path: string, options: { method?: string; body?: unknown; business?: boolean; idempotencyKey?: string } = {}): Promise<any> {
  if (!path.startsWith('/api/v1/')) throw new Error('Invalid gateway route')
  const credential = options.business ? await token() : backendToken()
  const headers: Record<string,string> = { Authorization:'Bearer ' + credential }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey
  const response = await fetch(base + path, { method:options.method || 'GET', credentials:'omit', headers,
    body:options.body === undefined ? undefined : JSON.stringify(options.body) })
  // Never automatically retry mutations or confirmations.
  return parse(response)
}
export async function downloadAsset(asset: Row, purpose: string) {
  const picker = (window as any).showSaveFilePicker
  if (!picker) throw new GatewayError('FILE_SYSTEM_API_REQUIRED','',400,'Large downloads require File System Access API')
  // Open within the user gesture, before network requests. No multi-gigabyte Blob buffering.
  const handle = await picker({ suggestedName:'meeting-' + String(asset.id) })
  const ticket = await api('/api/v1/assets/'+encodeURIComponent(asset.id)+'/download-tickets', {method:'POST', business:true,body:{purpose}})
  const response = await fetch(base+ticket.download_path, {credentials:'omit',headers:{Authorization:'Bearer '+await token()}})
  if (!response.ok) { await parse(response); return }
  if (!response.body) throw new Error('Streaming response required')
  const sink = await handle.createWritable()
  try { await response.body.pipeTo(sink) } catch (error) { try { await sink.abort() } catch {} throw error }
}
export function errorText(error: unknown): string {
  if (error instanceof GatewayError) return `${error.message} [${error.reason}] ${error.trace}`
  return error instanceof Error ? error.message : String(error)
}
