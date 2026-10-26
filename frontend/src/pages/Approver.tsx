import { ArrowLeft, Check, CircleCheck, FileText, Mail, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type ReqDetail } from '@/api/client'
import { useApprovers, useQueue, useReqAction, useRequisition } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { SourceSections, sourceSections } from '@/components/SourcePanel'
import { Avatar, Badge, Button, Empty, Kbd, Panel, Skeleton, Textarea } from '@/components/ui'
import { useLiveUpdates } from '@/lib/live'
import { cn, dateTime, money, qty } from '@/lib/format'

/** Inside the clerk app: a directory of approver views (stand-in for real sign-in). */
export function ApproverIndex() {
  const { data } = useApprovers()
  return (
    <>
      <PageHeader title="Approver view" sub="What each approver sees when they open the link in their notification. No sign-in in this prototype: the path stands in for the logged-in person." />
      <Page>
        <Panel className="divide-y divide-hairline">
          {data?.map((a) => (
            <Link key={a.id} to={`/approver/${a.id}`} target="_blank" className="flex items-center gap-3 px-5 py-3 hover:bg-sunken">
              <Avatar name={a.name} size={30} tone={a.pending ? 'accent' : 'neutral'} />
              <div className="flex-1">
                <p className="font-medium">{a.name}</p>
                <p className="text-[12.5px] text-muted">{a.role_label}</p>
              </div>
              {a.pending > 0 ? <Badge tone="accent">{a.pending} waiting</Badge> : <span className="text-[12.5px] text-faint">nothing waiting</span>}
            </Link>
          ))}
        </Panel>
      </Page>
    </>
  )
}

function ApproverShell({ emp, children }: { emp: string; children: ReactNode }) {
  useLiveUpdates()
  const { data } = useQueue(emp)
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-hairline bg-canvas/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[760px] items-center gap-3 px-4 py-3">
          <Link to={`/approver/${emp}`} className="text-[14px] font-semibold">
            Approvals
          </Link>
          <span className="ml-auto flex items-center gap-2 text-[13px] text-muted">
            {data && (
              <>
                <Avatar name={data.approver.name} size={24} />
                {data.approver.name}
              </>
            )}
          </span>
        </div>
      </header>
      {children}
    </div>
  )
}

export function ApproverQueue() {
  const emp = useParams().emp!
  const { data, isPending } = useQueue(emp)
  return (
    <ApproverShell emp={emp}>
      <div className="mx-auto max-w-[760px] px-4 py-8">
        <h1 className="text-[24px] font-semibold">{data ? (data.pending.length ? `${data.pending.length} waiting for you` : 'Nothing waiting for you') : 'Loading'}</h1>
        <p className="mt-1 text-[14px] text-muted">{data && `${data.approver.name}, ${data.approver.role.replace(/_/g, ' ')}`}</p>
        {isPending && <Skeleton className="mt-6 h-32" />}
        <Section title="Your decision" items={data?.pending ?? []} emp={emp} emptyText="You're all caught up." />
        {(data?.upcoming.length ?? 0) > 0 && <Section title="Coming to you later" items={data!.upcoming} emp={emp} />}
        {(data?.decided.length ?? 0) > 0 && <Section title="Decided" items={data!.decided} emp={emp} />}
      </div>
    </ApproverShell>
  )
}

function Section({ title, items, emp, emptyText }: { title: string; items: NonNullable<ReturnType<typeof useQueue>['data']>['pending']; emp: string; emptyText?: string }) {
  return (
    <section className="mt-8">
      <h2 className="mb-2 px-1 text-[15px] font-semibold">{title}</h2>
      <Panel className="divide-y divide-hairline overflow-hidden">
        {items.length === 0 && emptyText && <Empty icon={<CircleCheck size={24} />} title={emptyText} />}
        {items.map((it) => (
          <Link key={it.requisition.id} to={`/approver/${emp}/r/${it.requisition.id}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-sunken">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{it.requisition.title}</p>
              <p className="text-[12.5px] text-muted">
                {it.requisition.requester_name}, {it.requisition.supplier_name}, step {it.position} of {it.total} as {it.roles.join(' + ')}
              </p>
            </div>
            <span className="num text-[14px]">{money(it.requisition.po_total, it.requisition.currency)}</span>
            {it.status === 'approved' && <Badge tone="good">approved</Badge>}
            {it.status === 'rejected' && <Badge tone="bad">rejected</Badge>}
          </Link>
        ))}
      </Panel>
    </section>
  )
}

export function ApproverDecision() {
  const emp = useParams().emp!
  const id = Number(useParams().id)
  const { data: r } = useRequisition(id)
  const queue = useQueue(emp)
  const navigate = useNavigate()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [side, setSide] = useState<'email' | 'pdf' | null>(null)
  const reasonRef = useRef<HTMLTextAreaElement>(null)

  const approve = useReqAction(id, () => api.post<ReqDetail>(`/requisitions/${id}/approve`, { approver_id: emp }), 'Approved')
  const decline = useReqAction(id, (comment: string) => api.post<ReqDetail>(`/requisitions/${id}/decline`, { approver_id: emp, comment }), 'Rejected')

  const step = r?.steps.find((s) => s.approver_id === emp && (s.status === 'active' || s.status === 'waiting')) ?? r?.steps.find((s) => s.approver_id === emp)
  const myTurn = !!r && r.state === 'PENDING_APPROVAL' && step?.status === 'active'
  const isRequester = r?.requester_id === emp

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea') || e.metaKey || e.ctrlKey || !myTurn) return
      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault()
        approve.mutate(undefined)
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault()
        setRejecting(true)
        setTimeout(() => reasonRef.current?.focus(), 30)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [myTurn, approve])

  const nextPending = queue.data?.pending.find((p) => p.requisition.id !== id)
  const pdfAtt = r?.email.attachments.find((a) => a.content_type === 'application/pdf')
  // Body and non-PDF attachments; the quote has its own viewer.
  const emailSections = useMemo(() => (r ? sourceSections(r.email.source_text).filter((s) => !s.title.startsWith('EMAIL HEADERS') && !s.title.includes('(PDF')) : []), [r])
  const toggle = (v: 'email' | 'pdf') => setSide((s) => (s === v ? null : v))
  const prior = r?.steps.filter((s) => s.status === 'approved') ?? []
  const clerkNotes = r?.events.filter((e) => e.actor === 'clerk' && ['acknowledged', 'amount_decided', 'approver_assigned', 'field_edited', 'confirmed', 'supplier_created', 'corrected'].includes(e.kind)) ?? []
  // Order-only details (delivery date) aren't the approver's concern; the claim is shown as a note above.
  const openWarnings = r?.issues.filter((i) => i.status === 'open' && i.severity !== 'info' && !i.blocks_order && i.code !== 'bypass_claim') ?? []

  return (
    <ApproverShell emp={emp}>
      <div className={cn('mx-auto px-4 py-6 transition-[max-width]', side ? 'max-w-[1400px]' : 'max-w-[760px]')}>
        <div className={cn(side && 'grid gap-6 lg:grid-cols-[minmax(0,700px)_1fr]')}>
          <div>
            <Link to={`/approver/${emp}`} className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
              <ArrowLeft size={13} /> Your approvals
            </Link>
            {!r ? (
              <Skeleton className="h-96" />
            ) : (
              <>
                <p className="text-[13px] text-muted">
                  {r.public_id}, requested by {r.requester_name}
                </p>
                <h1 className="mt-1 text-[26px] leading-tight font-semibold">{r.title}</h1>
                <p className="num mt-3 text-[34px] leading-none font-semibold tracking-tight">{money(r.po_total, r.currency)}</p>
                <p className="mt-1.5 text-[13px] text-muted">
                  Net, excl. VAT
                  {r.currency !== 'CHF' && r.approval_amount_chf && <>; CHF {money(r.approval_amount_chf)} at {Number(r.fx_rate).toFixed(2)}</>}
                  {r.vat_amount && Number(r.vat_amount) > 0 && <>; VAT {money(r.vat_amount, r.currency)}</>}
                </p>

                <DecisionBar
                  r={r}
                  myTurn={myTurn}
                  isRequester={isRequester}
                  step={step}
                  rejecting={rejecting}
                  setRejecting={setRejecting}
                  reason={reason}
                  setReason={setReason}
                  reasonRef={reasonRef}
                  onApprove={() => approve.mutate(undefined)}
                  onReject={() => decline.mutate(reason, { onSuccess: () => setRejecting(false) })}
                  approving={approve.isPending}
                  declining={decline.isPending}
                  next={nextPending ? () => navigate(`/approver/${emp}/r/${nextPending.requisition.id}`) : undefined}
                />

                <Panel className="mt-6 divide-y divide-hairline">
                  <Fact label="Why you">
                    {step ? (
                      <>
                        Step {step.position} of {r.steps.length}, as {step.role_labels.join(' + ')}
                        {step.on_behalf_of_name && <span className="block text-[12.5px] text-accent">On behalf of {step.on_behalf_of_name}, who is the requester and can't approve.</span>}
                        {step.assigned_manually && <span className="block text-[12.5px] text-muted">Assigned by purchasing because the chain offered nobody else.</span>}
                      </>
                    ) : (
                      'You are not in this approval chain.'
                    )}
                  </Fact>
                  <Fact label="Approved so far">
                    {prior.length ? prior.map((s) => <span key={s.position} className="block">{s.approver_name} ({s.role_labels.join(' + ')}), {dateTime(s.decided_at)}{s.comment ? `: “${s.comment}”` : ''}</span>) : <span className="text-muted">You are first.</span>}
                  </Fact>
                  <Fact label="Supplier">
                    {r.supplier?.name ?? '—'} {r.supplier?.status === 'active' ? <Badge tone="good">active</Badge> : <Badge tone="bad">{r.supplier?.status}</Badge>}
                    {r.supplier?.created_by_clerk && <Badge className="ml-1">new, added by purchasing</Badge>}
                  </Fact>
                  <Fact label="Cost center">
                    {r.cost_center ? `${r.cost_center.code} ${r.cost_center.name}, owned by ${r.cost_center.owner_name}` : '—'}
                  </Fact>
                  <Fact label="Delivery">{r.delivery_date ? dateTime(r.delivery_date).split(',')[0] : r.delivery_date_text ? `“${r.delivery_date_text}”` : 'Not stated'}</Fact>
                  {r.prior_approval_claim && (
                    <Fact label="Note">
                      <span className="text-review">The email claims prior approval (“{r.prior_approval_claim}”). It doesn't replace this decision.</span>
                    </Fact>
                  )}
                </Panel>

                <h2 className="mt-7 mb-2 px-1 text-[15px] font-semibold">What is being bought</h2>
                <Panel className="divide-y divide-hairline">
                  {r.lines.map((l) => (
                    <div key={l.id} className="flex items-baseline gap-4 px-5 py-2.5 text-[13.5px]">
                      <span className="num w-24 shrink-0 text-muted">
                        {qty(l.quantity)} {l.unit}
                      </span>
                      <span className="min-w-0 flex-1">
                        {l.description}
                        {l.kind !== 'item' && <Badge className="ml-1.5">{l.kind}</Badge>}
                      </span>
                      <span className="num">{money(l.line_value)}</span>
                    </div>
                  ))}
                </Panel>

                {(clerkNotes.length > 0 || openWarnings.length > 0) && (
                  <>
                    <h2 className="mt-7 mb-2 px-1 text-[15px] font-semibold">From purchasing</h2>
                    <Panel className="divide-y divide-hairline text-[13px]">
                      {clerkNotes.map((e) => (
                        <p key={e.id} className="px-5 py-2.5 text-ink-2">
                          {e.message} <span className="text-muted">({dateTime(e.at)})</span>
                        </p>
                      ))}
                      {openWarnings.map((i) => (
                        <p key={i.id} className="px-5 py-2.5 text-ink-2">
                          {i.message}
                        </p>
                      ))}
                    </Panel>
                  </>
                )}
                <div className="mt-6 flex flex-wrap gap-2">
                  <Button onClick={() => toggle('email')}>
                    <Mail size={14} /> {side === 'email' ? 'Hide' : 'View'} the original email
                  </Button>
                  {pdfAtt && (
                    <Button onClick={() => toggle('pdf')}>
                      <FileText size={14} /> {side === 'pdf' ? 'Hide' : 'View'} the quote ({pdfAtt.filename})
                    </Button>
                  )}
                </div>
              </>
            )}
          </div>
          <AnimatePresence mode="wait">
            {side === 'pdf' && pdfAtt && (
              <motion.div key="pdf" initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.25 }} className="sticky top-20 h-[calc(100vh-110px)] overflow-hidden rounded-[var(--radius-panel)] shadow-[var(--shadow-panel)]">
                <iframe title={pdfAtt.filename} src={`/api/attachments/${pdfAtt.id}#view=FitH`} className="size-full bg-[#e9e9ec]" />
              </motion.div>
            )}
            {side === 'email' && r && (
              <motion.div key="email" initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.25 }} className="sticky top-20 h-[calc(100vh-110px)] overflow-y-auto rounded-[var(--radius-panel)] bg-surface px-5 py-4 shadow-[var(--shadow-panel)]">
                <div className="mb-4 space-y-0.5 text-[12.5px]">
                  <p>
                    <span className="text-muted">From </span>
                    {r.email.from_name} <span className="text-muted">&lt;{r.email.from_email}&gt;</span>
                  </p>
                  <p>
                    <span className="text-muted">Sent </span>
                    {dateTime(r.email.sent_at)}
                  </p>
                  <p>
                    <span className="text-muted">Subject </span>
                    {r.email.subject}
                  </p>
                  {r.redactions.length > 0 && <p className="pt-1 text-muted">Sensitive values such as bank and card numbers are hidden here.</p>}
                </div>
                <SourceSections sections={emailSections} redacted={r.redactions} mask />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </ApproverShell>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_minmax(0,1fr)] gap-3 px-5 py-3 text-[13.5px]">
      <span className="text-muted">{label}</span>
      <div>{children}</div>
    </div>
  )
}

function DecisionBar(props: {
  r: ReqDetail
  myTurn: boolean
  isRequester: boolean
  step: ReqDetail['steps'][number] | undefined
  rejecting: boolean
  setRejecting: (v: boolean) => void
  reason: string
  setReason: (v: string) => void
  reasonRef: React.RefObject<HTMLTextAreaElement | null>
  onApprove: () => void
  onReject: () => void
  approving: boolean
  declining: boolean
  next?: () => void
}) {
  const { r, myTurn, isRequester, step } = props
  const active = r.steps.find((s) => s.status === 'active')
  let status: ReactNode = null
  if (isRequester) status = 'You raised this requisition, so you can never approve it.'
  else if (step?.status === 'approved') status = <span className="flex items-center gap-1.5 text-good"><Check size={15} /> You approved this {dateTime(step.decided_at)}.</span>
  else if (step?.status === 'rejected') status = <span className="flex items-center gap-1.5 text-bad"><X size={15} /> You rejected this: {step.comment}</span>
  else if (r.state === 'PENDING_APPROVAL' && step?.status === 'waiting') status = `Not your turn yet: waiting for ${active?.approver_name} (step ${active?.position}).`
  else if (r.state === 'REJECTED') status = `Rejected${r.rejected_by_name ? ` by ${r.rejected_by_name}` : ''}: ${r.rejection_reason}`
  else if (!myTurn) status = `This requisition is ${r.state_label.toLowerCase()}.`

  return (
    <div className="mt-6 rounded-[var(--radius-panel)] bg-surface p-4 shadow-[var(--shadow-panel)]">
      {myTurn ? (
        props.rejecting ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              props.onReject()
            }}
          >
            <label htmlFor="why" className="mb-1.5 block text-[13px] font-medium">
              Why are you rejecting it?
            </label>
            <Textarea id="why" ref={props.reasonRef} value={props.reason} onChange={(e) => props.setReason(e.target.value)} placeholder="The requester and purchasing will see this." />
            <div className="mt-3 flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => props.setRejecting(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="danger" disabled={!props.reason.trim()} loading={props.declining}>
                Reject
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="good" className="h-10 px-5 text-[14px]" onClick={props.onApprove} loading={props.approving}>
              <Check size={15} /> Approve <Kbd className="ml-1 border-white/30 bg-white/15 text-white">A</Kbd>
            </Button>
            <Button variant="danger" className="h-10 px-5 text-[14px]" onClick={() => props.setRejecting(true)}>
              Reject <Kbd className="ml-1">R</Kbd>
            </Button>
            <span className="text-[12.5px] text-muted">
              {r.steps.length - (step?.position ?? 0) > 0 ? `${r.steps.length - (step?.position ?? 0)} more after you` : 'You are the last approver; approving completes the chain.'}
            </span>
          </div>
        )
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 text-[13.5px]">
          <span>{status}</span>
          {props.next && (
            <Button variant="primary" onClick={props.next}>
              Next waiting for you
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
