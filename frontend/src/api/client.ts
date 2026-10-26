import type { components } from './schema'

type S = components['schemas']
export type ReqSummary = S['ReqSummary']
export type ReqDetail = S['ReqDetail']
export type LineOut = S['LineOut']
export type IssueOut = S['IssueOut']
export type StepOut = S['StepOut']
export type Prov = S['Prov']
export type Dashboard = S['DashboardOut']
export type Workflow = S['WorkflowOut']
export type Master = S['MasterOut']
export type PurchaseOrder = S['PurchaseOrderOut']
export type Settings = S['SettingsOut']
export type Status = S['StatusOut']
export type Notification = S['NotificationOut']
export type Sample = S['SampleOut']
export type Approver = S['ApproverOut']
export type Queue = S['QueueOut']
export type LineIn = S['LineIn']
export type FieldsPatch = S['FieldsPatch']

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const init: RequestInit = { method, headers: { ...headers } }
  if (body instanceof Blob || body instanceof ArrayBuffer) {
    init.body = body as BodyInit
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    let message = `Request failed (HTTP ${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) => request<T>('POST', path, body ?? {}, headers),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
}
