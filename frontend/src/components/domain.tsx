import { Check, CircleAlert, CircleHelp, Lightbulb, PenLine, ShieldCheck, X } from 'lucide-react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import type { Prov, ReqDetail, ReqSummary, StepOut } from '@/api/client'
import { cn, dateTime, MAIN_PATH, STAGE_LABEL, STATE_LABEL, STATE_TONE } from '@/lib/format'
import { Avatar, Badge, Popover, Tip } from './ui'

// ---------------------------------------------------------------- state

export function StatePill({ state, stage }: { state: string; stage?: string | null }) {
  if (state === 'PROCESSING' || state === 'INBOX' || state === 'EXTRACTED') {
    return (
      <Badge tone="neutral">
        <span className="pulse-dot size-1.5 rounded-full bg-accent" />
        {stage ? STAGE_LABEL[stage] ?? 'Processing' : state === 'INBOX' ? 'Queued' : 'Processing'}
      </Badge>
    )
  }
  return (
    <Badge tone={STATE_TONE[state]} dot>
      {STATE_LABEL[state] ?? state}
    </Badge>
  )
}

/** The route in miniature: six segments for the main path, filled up to where the case is. */
export function RouteMini({ r }: { r: ReqSummary }) {
  const exits: Record<string, number> = { REJECTED: 3, CLOSED_DUPLICATE: 2, EXTRACTED: 1 }
  const at = exits[r.state] ?? MAIN_PATH.indexOf(r.state as (typeof MAIN_PATH)[number])
  const tone = STATE_TONE[r.state]
  const fill = {
    neutral: 'bg-ink-2/40',
    accent: 'bg-accent',
    review: 'bg-review',
    good: 'bg-good',
    bad: 'bg-bad',
  }[tone]
  return (
    <div className="flex items-center gap-[3px]" aria-label={`At ${STATE_LABEL[r.state]}`}>
      {MAIN_PATH.map((s, i) => (
        <span
          key={s}
          className={cn(
            'h-1.5 w-3 rounded-full',
            i < at && 'bg-ink-2/25',
            i === at && fill,
            i > at && 'bg-black/[0.07]',
            i === at && r.state === 'PROCESSING' && 'pulse-dot',
          )}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- the route

type Station = {
  key: string
  status: 'done' | 'current' | 'future' | 'failed' | 'skipped'
  title: ReactNode
  sub?: ReactNode
  marker?: ReactNode
  avatar?: { name: string | null | undefined; tone: 'neutral' | 'accent' | 'good' | 'bad' | 'muted' }
  icon?: ReactNode
}

function stepStatus(s: StepOut): Station['status'] {
  if (s.status === 'approved') return 'done'
  if (s.status === 'active') return 'current'
  if (s.status === 'rejected') return 'failed'
  return 'future'
}

/**
 * The signature element: one line from the email's arrival, through review and every
 * approver as a station, to the purchase order. Where the case is now is the only
 * thing in colour.
 */
export function Route({ r }: { r: ReqDetail }) {
  const st = r.state
  const reviewed = !['INBOX', 'PROCESSING', 'EXTRACTED', 'NEEDS_REVIEW'].includes(st)
  const stations: Station[] = [
    {
      key: 'received',
      status: 'done',
      title: 'Received',
      sub: dateTime(r.sent_at ?? r.received_at),
      icon: <Check size={12} strokeWidth={3} />,
    },
  ]
  if (st === 'PROCESSING' || st === 'INBOX' || st === 'EXTRACTED') {
    stations.push({ key: 'proc', status: 'current', title: 'Processing', sub: r.stage ? STAGE_LABEL[r.stage] : 'Queued' })
  } else {
    stations.push({
      key: 'review',
      status: st === 'NEEDS_REVIEW' ? 'current' : st === 'CLOSED_DUPLICATE' ? 'failed' : 'done',
      title: st === 'NEEDS_REVIEW' ? 'With purchasing' : st === 'CLOSED_DUPLICATE' ? 'Closed as duplicate' : 'Checked',
      sub:
        st === 'NEEDS_REVIEW'
          ? `${r.issue_counts.blocking} to resolve`
          : st === 'CLOSED_DUPLICATE'
            ? r.linked_to_public_id
            : r.issue_counts.blocking === 0
              ? 'Nothing blocking'
              : undefined,
      icon: st === 'CLOSED_DUPLICATE' ? <X size={12} strokeWidth={3} /> : reviewed ? <Check size={12} strokeWidth={3} /> : <PenLine size={11} />,
    })
  }

  const live = !r.steps_are_preview
  for (const s of r.steps) {
    const status: Station['status'] = live ? stepStatus(s) : 'future'
    stations.push({
      key: `step-${s.position}`,
      status: st === 'CLOSED_DUPLICATE' ? 'skipped' : status,
      title: s.approver_name ?? 'Needs an approver',
      sub: s.role_labels.join(' + '),
      marker: s.on_behalf_of_name ? (
        <Tip content={s.note ?? ''}>
          <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 text-[11px] text-accent">on behalf of {s.on_behalf_of_name}</span>
        </Tip>
      ) : s.assigned_manually ? (
        <span className="mt-1 inline-flex rounded-full bg-black/5 px-1.5 text-[11px] text-ink-2">assigned by purchasing</span>
      ) : !s.approver_id ? (
        <span className="mt-1 inline-flex rounded-full bg-review-soft px-1.5 text-[11px] text-review">assign by hand</span>
      ) : s.status === 'approved' && s.decided_at ? (
        <span className="mt-0.5 block text-[11px] text-muted">{dateTime(s.decided_at)}</span>
      ) : undefined,
      avatar: {
        name: s.approver_name,
        tone: status === 'done' ? 'good' : status === 'failed' ? 'bad' : status === 'current' ? 'accent' : s.approver_id ? 'neutral' : 'muted',
      },
    })
  }
  if (!r.steps.length && st !== 'CLOSED_DUPLICATE') {
    stations.push({ key: 'chain', status: 'future', title: 'Approval chain', sub: 'Built once amount, cost center and requester are known' })
  }

  if (st === 'REJECTED') {
    stations.push({ key: 'rejected', status: 'failed', title: 'Rejected', sub: r.rejected_by_name ?? 'by purchasing', icon: <X size={12} strokeWidth={3} /> })
  } else if (st !== 'CLOSED_DUPLICATE') {
    stations.push({
      key: 'approved',
      status: st === 'APPROVED' ? 'current' : st === 'ORDERED' ? 'done' : 'future',
      title: 'Approved',
      sub: st === 'APPROVED' ? (r.order_blockers.length ? 'Details missing for the order' : 'Ready to order') : undefined,
      icon: <Check size={12} strokeWidth={3} />,
    })
    stations.push({
      key: 'ordered',
      status: st === 'ORDERED' ? 'done' : 'future',
      title: 'Ordered',
      sub: r.po_number ?? undefined,
      icon: <ShieldCheck size={12} />,
    })
  }

  return (
    <div className="-mx-1 overflow-x-auto px-1 pb-1">
      <ol className="flex min-w-max items-start">
        {stations.map((s, i) => (
          <li key={s.key} className="flex items-start">
            {i > 0 && <Connector from={stations[i - 1].status} to={s.status} />}
            <StationView s={s} />
          </li>
        ))}
      </ol>
    </div>
  )
}

function Connector({ from, to }: { from: Station['status']; to: Station['status'] }) {
  const solid = from === 'done' && to !== 'future' && to !== 'skipped'
  return (
    <div className="relative mt-[13px] h-px w-10 shrink-0 sm:w-14">
      <div className={cn('absolute inset-0', solid ? 'bg-ink-2/35' : 'border-t border-dashed border-hairline-strong')} />
      {solid && to === 'current' && (
        <motion.div
          className="absolute inset-y-0 left-0 bg-accent"
          initial={{ width: 0 }}
          animate={{ width: '100%' }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      )}
    </div>
  )
}

function StationView({ s }: { s: Station }) {
  const ring = {
    done: 'bg-ink-2 text-white',
    current: 'bg-accent text-white ring-4 ring-accent-soft',
    future: 'bg-surface text-faint shadow-[0_0_0_1px_var(--color-hairline-strong)]',
    failed: 'bg-bad text-white ring-4 ring-bad-soft',
    skipped: 'bg-surface text-faint shadow-[0_0_0_1px_var(--color-hairline)]',
  }[s.status]
  return (
    <div className={cn('flex w-[124px] flex-col items-center text-center', s.status === 'skipped' && 'opacity-50')}>
      {s.avatar ? (
        <span className={cn('rounded-full', s.status === 'current' && 'ring-4 ring-accent-soft', s.status === 'failed' && 'ring-4 ring-bad-soft')}>
          <Avatar name={s.avatar.name} size={27} tone={s.avatar.tone} />
        </span>
      ) : (
        <span className={cn('flex size-[27px] items-center justify-center rounded-full', ring)}>{s.status === 'future' ? <span className="size-1.5 rounded-full bg-hairline-strong" /> : s.icon}</span>
      )}
      <span className={cn('mt-2 text-[12.5px] leading-tight font-medium', s.status === 'future' ? 'text-muted' : 'text-ink', s.status === 'current' && 'text-accent', s.status === 'failed' && 'text-bad')}>
        {s.title}
      </span>
      {s.sub && <span className="mt-0.5 text-[11.5px] leading-tight text-muted">{s.sub}</span>}
      {s.marker}
    </div>
  )
}

// ---------------------------------------------------------------- provenance

const PROV: Record<string, { label: string; tone: 'neutral' | 'accent' | 'review' | 'good' | 'bad'; icon: ReactNode }> = {
  confirmed: { label: 'Confirmed', tone: 'good', icon: <Check size={11} strokeWidth={3} /> },
  from_document: { label: 'From document', tone: 'neutral', icon: null },
  computed: { label: 'Computed', tone: 'neutral', icon: null },
  suggested: { label: 'Suggested', tone: 'accent', icon: <Lightbulb size={11} /> },
  unverified: { label: 'Unverified', tone: 'review', icon: <CircleHelp size={11} /> },
  missing: { label: 'Missing', tone: 'bad', icon: <CircleAlert size={11} /> },
  conflict: { label: 'Conflict', tone: 'bad', icon: <CircleAlert size={11} /> },
}

const SOURCE_LABEL: Record<string, string> = {
  clerk: 'Set by purchasing',
  document: 'Read from the email or attachment by the AI',
  master_data: 'Matched in the master data',
  computed: 'Computed by the system',
  ai: 'Suggested by the AI',
  thread: 'Derived from the email thread',
  sender: 'Sender of the email',
}

function provStatus(p?: Prov | null, fallback = 'from_document') {
  if (!p) return fallback
  if (p.source === 'clerk') return 'confirmed'
  return p.status ?? fallback
}

/** A small status chip with a "why" popover: evidence, grounding, check probability. */
export function ProvChip({ p, fallback, onEvidence, compact }: { p?: Prov | null; fallback?: string; onEvidence?: (text: string) => void; compact?: boolean }) {
  const status = provStatus(p, fallback)
  const meta = PROV[status] ?? PROV.from_document
  const verified = p?.check != null && p.check >= 0.8 && status !== 'confirmed'
  return (
    <Popover
      width={300}
      trigger={
        <button type="button" className="inline-flex items-center gap-1 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-label={`${meta.label}: why?`}>
          <Badge tone={meta.tone} className={cn(compact && 'h-[18px] px-1.5 text-[10.5px]')}>
            {meta.icon}
            {meta.label}
          </Badge>
          {verified && (
            <span className="inline-flex h-[18px] items-center gap-0.5 rounded-full bg-good-soft px-1.5 text-[10.5px] font-medium text-good">
              <ShieldCheck size={10} /> {Math.round((p!.check as number) * 100)}%
            </span>
          )}
        </button>
      }
    >
      <p className="font-medium">{meta.label}</p>
      <p className="mt-1 text-muted">{p?.source ? SOURCE_LABEL[p.source] ?? p.source : status === 'missing' ? 'Not found in the email or master data.' : 'Read from the email or attachment.'}</p>
      {p?.reason && <p className="mt-2 text-ink-2">{p.reason}</p>}
      {p?.grounded === false && p.source !== 'clerk' && <p className="mt-2 text-review">Not found verbatim in the source, so it isn't trusted until someone checks it.</p>}
      {p?.grounded === true && p.source === 'document' && <p className="mt-2 text-good">Found in the source text.</p>}
      {p?.check != null && (
        <p className="mt-2 text-ink-2">
          Independent check: <span className="num font-medium">{Math.round(p.check * 100)}%</span> likely to match the document.
        </p>
      )}
      {p?.evidence && (
        <button type="button" onClick={() => onEvidence?.(p.evidence!)} className="mt-2.5 block w-full rounded-lg bg-sunken p-2 text-left text-[12.5px] text-ink-2 shadow-[0_0_0_0.5px_var(--color-hairline)] hover:bg-accent-soft">
          “{p.evidence}”
          <span className="mt-1 block text-[11.5px] text-accent">Show in source</span>
        </button>
      )}
    </Popover>
  )
}
