import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...v: ClassValue[]) => twMerge(clsx(v))

export function money(value: string | number | null | undefined, currency?: string | null, opts: { decimals?: boolean } = {}) {
  if (value === null || value === undefined || value === '') return '—'
  const n = typeof value === 'number' ? value : Number(value)
  const s = n.toLocaleString('de-CH', {
    minimumFractionDigits: opts.decimals === false ? 0 : 2,
    maximumFractionDigits: opts.decimals === false ? 0 : 2,
  })
  return currency ? `${currency} ${s}` : s
}

export function qty(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return n.toLocaleString('de-CH', { maximumFractionDigits: 4 })
}

const dateFmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const timeFmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export const date = (v: string | null | undefined) => (v ? dateFmt.format(new Date(v)) : '—')
export const dateTime = (v: string | null | undefined) => (v ? timeFmt.format(new Date(v)) : '—')

export function ago(v: string | null | undefined) {
  if (!v) return ''
  const s = (Date.now() - new Date(v).getTime()) / 1000
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return dateFmt.format(new Date(v))
}

export const initials = (name?: string | null) =>
  (name ?? '?')
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

/** The happy path a requisition travels; side exits (rejected, duplicate) hang off it. */
export const MAIN_PATH = ['INBOX', 'PROCESSING', 'NEEDS_REVIEW', 'PENDING_APPROVAL', 'APPROVED', 'ORDERED'] as const

export const STATE_LABEL: Record<string, string> = {
  INBOX: 'Inbox',
  PROCESSING: 'Processing',
  EXTRACTED: 'Extracted',
  NEEDS_REVIEW: 'Needs review',
  PENDING_APPROVAL: 'Pending approval',
  APPROVED: 'Approved',
  ORDERED: 'Ordered',
  REJECTED: 'Rejected',
  CLOSED_DUPLICATE: 'Closed as duplicate',
}

export type Tone = 'neutral' | 'accent' | 'review' | 'good' | 'bad'

export const STATE_TONE: Record<string, Tone> = {
  INBOX: 'neutral',
  PROCESSING: 'neutral',
  EXTRACTED: 'neutral',
  NEEDS_REVIEW: 'review',
  PENDING_APPROVAL: 'accent',
  APPROVED: 'good',
  ORDERED: 'good',
  REJECTED: 'bad',
  CLOSED_DUPLICATE: 'neutral',
}

export const STAGES = ['parse', 'redact', 'extract', 'verify', 'match', 'route'] as const
export const STAGE_LABEL: Record<string, string> = {
  parse: 'Reading the email',
  redact: 'Redacting sensitive data',
  extract: 'Extracting with AI',
  verify: 'Checking values',
  match: 'Matching master data',
  route: 'Routing',
}
