import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bot, ExternalLink, FileText, GitMerge, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Group, Panel as ResizablePanel, Separator } from 'react-resizable-panels'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, type ReqDetail } from '@/api/client'
import { keys, useReqAction, useRequisition, useRequisitions, useSettings } from '@/api/hooks'
import { AmountsPanel, FieldsPanel, LinesPanel } from '@/components/DetailsPanel'
import { Route, StatePill } from '@/components/domain'
import { IssuePanel } from '@/components/IssuePanel'
import { allAttachments, SourcePanel, type SourceTab } from '@/components/SourcePanel'
import { Badge, Button, Dialog, Input, Kbd, Label, Panel, Skeleton, Textarea, Tip } from '@/components/ui'
import { cn, date, dateTime, money } from '@/lib/format'

function useWide(query = '(min-width: 1180px)') {
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const on = () => setWide(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [query])
  return wide
}

export function RequisitionPage() {
  const id = Number(useParams().id)
  // Keyed by id: moving to another requisition starts with fresh view state.
  return <RequisitionView key={id} id={id} />
}

function RequisitionView({ id }: { id: number }) {
  const { data: r, isPending, error } = useRequisition(id)
  const [tab, setTab] = useState<SourceTab>('email')
  const [active, setActive] = useState<string | null>(null)
  const [editingLines, setEditingLines] = useState(false)
  const wide = useWide()

  const evidence = useMemo(() => {
    if (!r) return []
    const out = new Set<string>()
    Object.values(r.provenance).forEach((p) => p.evidence && out.add(p.evidence))
    r.lines.forEach((l) => l.source_quote && out.add(l.source_quote))
    r.stated_totals.forEach((t) => t.evidence && out.add(t.evidence))
    return [...out]
  }, [r])

  if (error) return <div className="p-10 text-center text-muted">{error.message}</div>
  if (isPending || !r) return <DetailSkeleton />

  // The editor sits below the fields, usually out of view: bring it up, also when it is already open.
  const editLines = () => {
    setEditingLines(true)
    requestAnimationFrame(() => document.getElementById('line-editor')?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }

  const showEvidence = (t: string) => {
    setTab('email')
    setActive(null)
    requestAnimationFrame(() => setActive(t))
  }

  const main = (
    <div className="space-y-5 p-4 sm:p-6">
      <IssuePanel r={r} onEditLines={editLines} />
      {r.notes.length > 0 && (
        <Panel className="px-5 py-4">
          <h2 className="mb-2 flex items-center gap-2 text-[15px] font-semibold">
            Worth knowing <span className="text-[12px] font-normal text-muted">from the email, noted by the AI</span>
          </h2>
          <ul className="list-disc space-y-1 pl-4 text-[13px] text-ink-2 marker:text-faint">
            {r.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </Panel>
      )}
      <FieldsPanel r={r} onEvidence={showEvidence} />
      <LinesPanel r={r} editing={editingLines} setEditing={setEditingLines} onEvidence={showEvidence} />
      <AmountsPanel r={r} />
      <Activity r={r} />
    </div>
  )
  const source = <SourcePanel r={r} tab={tab} setTab={setTab} evidence={evidence} active={active} />

  return (
    <div className="flex h-screen flex-col">
      <Header r={r} onPdf={() => setTab('pdf-0')} />
      {wide ? (
        <Group orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel defaultSize="58" minSize="40" className="overflow-y-auto">
            {main}
          </ResizablePanel>
          <Separator className="w-px bg-hairline transition-colors outline-none hover:bg-accent data-[separator=active]:bg-accent" />
          <ResizablePanel defaultSize="42" minSize="26" className="bg-surface">
            {source}
          </ResizablePanel>
        </Group>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {main}
          <div className="mx-4 mb-6 h-[70vh] overflow-hidden rounded-[var(--radius-panel)] bg-surface shadow-[var(--shadow-panel)] sm:mx-6">{source}</div>
        </div>
      )}
    </div>
  )
}

function Header({ r, onPdf }: { r: ReqDetail; onPdf: () => void }) {
  const [rejectOpen, setRejectOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const submit = useReqAction(r.id, () => api.post<ReqDetail>(`/requisitions/${r.id}/submit`), (d) =>
    d.state === 'PENDING_APPROVAL' ? `Sent to ${d.current_step?.approver_name}` : 'Still needs review',
  )
  const order = useReqAction(r.id, () => api.post<ReqDetail>(`/requisitions/${r.id}/order`), (d) => (d.state === 'ORDERED' ? `Ordered as ${d.po_number}` : 'The order failed; see the issue'))
  const reprocess = useReqAction(r.id, async () => {
    await api.post(`/requisitions/${r.id}/reprocess`)
    return api.get<ReqDetail>(`/requisitions/${r.id}`)
  }, 'Processing again')
  const blocking = r.issue_counts.blocking
  const hasPdf = allAttachments(r).some((a) => a.content_type === 'application/pdf')
  const active = r.steps.find((s) => s.status === 'active')
  const navigate = useNavigate()
  const location = useLocation()

  // Esc goes back to where we came from (the list, keeping its view), or to the list on a direct visit.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest('input, textarea, select, [cmdk-root]')
      // Dialogs and popovers claim Esc first and mark it handled.
      if (e.key !== 'Escape' || e.defaultPrevented || typing) return
      if (location.key !== 'default') navigate(-1)
      else navigate('/requisitions')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [location.key, navigate])

  return (
    <header className="z-20 shrink-0 border-b border-hairline bg-canvas/85 backdrop-blur-xl backdrop-saturate-150">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3 px-4 pt-3.5 sm:px-6">
        <div className="min-w-0 flex-1">
          <Link to="/requisitions" className="mb-1 inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-ink">
            <ArrowLeft size={13} /> Requisitions <Kbd className="ml-1">Esc</Kbd>
          </Link>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="truncate text-[20px] font-semibold">{r.title || r.email.subject}</h1>
            <StatePill state={r.state} stage={r.stage} />
          </div>
          <p className="mt-1 text-[13px] text-muted">
            <span className="num">{r.public_id}</span>, requested by <span className="text-ink-2">{r.requester_name ?? 'unknown'}</span>
            {r.po_total && (
              <>
                , <span className="num text-ink-2">{money(r.po_total, r.currency)}</span>
                {r.currency !== 'CHF' && r.approval_amount_chf && <span className="num"> (CHF {money(r.approval_amount_chf, null, { decimals: false })} for approval)</span>}
              </>
            )}
            {r.linked_to_public_id && (
              <>
                , linked to{' '}
                <Link to={`/r/${r.linked_to_id}`} className="text-accent">
                  {r.linked_to_public_id}
                </Link>
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-5">
          {hasPdf && (
            <Button variant="ghost" onClick={onPdf}>
              <FileText size={14} /> View PDF
            </Button>
          )}
          {r.state === 'NEEDS_REVIEW' && (
            <Button variant="ghost" onClick={() => reprocess.mutate(undefined)} loading={reprocess.isPending}>
              <RefreshCw size={13} /> Re-run extraction
            </Button>
          )}
          {['NEEDS_REVIEW', 'PENDING_APPROVAL'].includes(r.state) && (
            <Tip content="This email belongs to another requisition: copy what it states there and close this one.">
              <Button variant="ghost" onClick={() => setMergeOpen(true)}>
                <GitMerge size={13} /> Merge into…
              </Button>
            </Tip>
          )}
          {['NEEDS_REVIEW', 'PENDING_APPROVAL'].includes(r.state) && (
            <Button variant="danger" onClick={() => setRejectOpen(true)}>
              Reject
            </Button>
          )}
          {(r.state === 'NEEDS_REVIEW' || r.state === 'REJECTED') && (
            <Tip content={r.can_submit ? 'Builds the approval chain and asks the first approver.' : `Resolve the ${blocking} blocking issue${blocking === 1 ? '' : 's'} first.`}>
              <span>
                <Button variant="primary" disabled={!r.can_submit} onClick={() => submit.mutate(undefined)} loading={submit.isPending}>
                  {r.state === 'REJECTED' ? 'Resubmit from step 1' : 'Send to approval'}
                </Button>
              </span>
            </Tip>
          )}
          {r.state === 'PENDING_APPROVAL' && active?.approver_id && (
            <Link to={`/approver/${active.approver_id}/r/${r.id}`} target="_blank">
              <Button>
                <ExternalLink size={13} /> Open as {active.approver_name}
              </Button>
            </Link>
          )}
          {r.state === 'APPROVED' && (
            <Tip content={r.order_blockers.length ? r.order_blockers.join(' ') : 'Books the purchase order in the ERP.'}>
              <span>
                <Button variant="primary" disabled={r.order_blockers.length > 0} onClick={() => order.mutate(undefined)} loading={order.isPending}>
                  Place order
                </Button>
              </span>
            </Tip>
          )}
        </div>
      </div>
      <div className="px-4 pt-4 pb-3 sm:px-6">
        <Route r={r} />
        {r.state === 'REJECTED' && r.rejection_reason && (
          <p className="mt-2 text-[13px] text-bad">
            Rejected{r.rejected_by_name ? ` by ${r.rejected_by_name}` : ' by purchasing'}: {r.rejection_reason}. Correct it and resubmit; the chain starts again from step 1.
          </p>
        )}
        {r.steps_are_preview && r.steps.length > 0 && r.state === 'NEEDS_REVIEW' && <p className="mt-1 text-[12px] text-muted">The approvers shown are the chain this requisition will get once it is sent.</p>}
      </div>
      <RejectDialog r={r} open={rejectOpen} onOpenChange={setRejectOpen} />
      {mergeOpen && <MergeDialog r={r} onOpenChange={setMergeOpen} />}
    </header>
  )
}

const MERGEABLE_INTO = ['NEEDS_REVIEW', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED']

/** Pick the requisition this email belongs to. The likely ones first: the linked one, then the same requester's. */
function MergeDialog({ r, onOpenChange }: { r: ReqDetail; onOpenChange: (v: boolean) => void }) {
  const [q, setQ] = useState('')
  const { data } = useRequisitions()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const merge = useReqAction(r.id, (public_id: string) => api.post<ReqDetail>(`/requisitions/${r.id}/merge`, { public_id }), (d) => `Merged into ${d.linked_to_public_id}`)

  const candidates = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const rank = (x: { id: number; requester_id: string | null }) => (x.id === r.linked_to_id ? 0 : x.requester_id && x.requester_id === r.requester_id ? 1 : 2)
    return (data ?? [])
      .filter((x) => x.id !== r.id && x.linked_to_id !== r.id && MERGEABLE_INTO.includes(x.state))
      .filter((x) => !needle || [x.public_id, x.title, x.requester_name, x.supplier_name ?? x.supplier_name_doc].some((v) => v?.toLowerCase().includes(needle)))
      .sort((a, b) => rank(a) - rank(b) || b.received_at.localeCompare(a.received_at))
      .slice(0, 8)
  }, [data, q, r.id, r.linked_to_id, r.requester_id])

  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      width={560}
      title={`Merge ${r.public_id} into another requisition`}
      description="What this email states (supplier, cost center, dates, line items) is copied onto the one you pick, and its email and attachments become part of that requisition's source. This one is closed; the other one's approval chain starts again."
    >
      <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by ID, title, requester or supplier" aria-label="Search requisitions" />
      <ul className="mt-3 max-h-[340px] divide-y divide-hairline overflow-y-auto rounded-lg text-[12.5px] shadow-[0_0_0_0.5px_var(--color-hairline-strong)]">
        {candidates.map((x) => (
          <li key={x.id} className="flex items-center gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate">
                <span className="num font-medium">{x.public_id}</span> <span className="text-ink">{x.title || x.source_name}</span>
                {x.id === r.linked_to_id && <span className="text-accent"> (linked)</span>}
              </p>
              <p className="truncate text-[12px] text-muted">
                {[x.requester_name, x.supplier_name ?? x.supplier_name_doc, date(x.sent_at ?? x.received_at)].filter(Boolean).join(', ')}
                {x.po_total && <span className="num">, {money(x.po_total, x.currency)}</span>}
              </p>
            </div>
            <StatePill state={x.state} stage={x.stage} />
            <Button
              size="sm"
              onClick={() =>
                merge.mutate(x.public_id, {
                  onSuccess: () => {
                    qc.invalidateQueries({ queryKey: keys.detail(x.id) })
                    onOpenChange(false)
                    navigate(`/r/${x.id}`)
                  },
                })
              }
              loading={merge.isPending && merge.variables === x.public_id}
            >
              Merge into this
            </Button>
          </li>
        ))}
        {candidates.length === 0 && <li className="px-3 py-4 text-center text-muted">No open requisition matches.</li>}
      </ul>
    </Dialog>
  )
}

function RejectDialog({ r, open, onOpenChange }: { r: ReqDetail; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [reason, setReason] = useState('')
  const reject = useReqAction(r.id, (reason: string) => api.post<ReqDetail>(`/requisitions/${r.id}/reject`, { reason }), 'Rejected')
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={`Reject ${r.public_id}`} description="The reason is kept with the requisition and sent to the requester.">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          reject.mutate(reason, { onSuccess: () => onOpenChange(false) })
        }}
      >
        <Label htmlFor="reason">Reason</Label>
        <Textarea id="reason" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: the supplier is blocked; order from an approved alternative." />
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" disabled={!reason.trim()} loading={reject.isPending}>
            Reject
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function Activity({ r }: { r: ReqDetail }) {
  const [tab, setTab] = useState<'log' | 'ai'>('log')
  const settings = useSettings()
  const rerun = useReqAction(r.id, () => api.post<ReqDetail>(`/requisitions/${r.id}/rerun-checks`), 'Checks re-run')
  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-3">
        <div className="flex gap-1">
          <TabBtn on={tab === 'log'} onClick={() => setTab('log')}>
            Activity
          </TabBtn>
          <TabBtn on={tab === 'ai'} onClick={() => setTab('ai')}>
            AI runs <span className="num text-faint">{r.llm_runs.length}</span>
          </TabBtn>
        </div>
        {settings.data?.decision_checks_enabled && r.extraction_ok && (
          <Button size="sm" variant="ghost" onClick={() => rerun.mutate(undefined)} loading={rerun.isPending}>
            <ShieldCheck size={13} /> Re-run checks
          </Button>
        )}
      </div>
      {tab === 'log' ? (
        <ol className="border-t border-hairline px-5 py-3">
          {r.events.map((e) => (
            <li key={e.id} className="relative flex gap-3 pb-3 pl-4 text-[13px] last:pb-0">
              <span className="absolute top-[7px] left-0 size-1.5 rounded-full bg-hairline-strong" />
              <span className="absolute top-[15px] bottom-0 left-[2.5px] w-px bg-hairline last:hidden" />
              <div className="min-w-0 flex-1">
                <p className="text-ink-2">{e.message}</p>
                <p className="text-[12px] text-muted">
                  {e.actor_name}, {dateTime(e.at)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <ul className="divide-y divide-hairline border-t border-hairline text-[13px]">
          {r.redactions.length > 0 && (
            <li className="flex items-center gap-2 px-5 py-2.5 text-ink-2">
              <ShieldOff size={14} className="text-accent" /> Redacted before any AI call: {r.redactions.map((x) => x.placeholder).join(', ')}
            </li>
          )}
          {r.llm_runs.map((run) => (
            <li key={run.id} className="px-5 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Bot size={14} className="text-muted" />
                <span className="font-medium">{run.kind === 'extract' ? 'Extraction' : 'Decision checks'}</span>
                <span className="text-muted">
                  {run.model}, {run.prompt_version}
                  {run.attempt > 1 && `, retry ${run.attempt - 1}`}
                </span>
                {run.cached && <Badge>from cache</Badge>}
                {run.error ? <Badge tone="bad">failed</Badge> : run.ok ? <Badge tone="good">valid</Badge> : <Badge tone="review">invalid</Badge>}
                <span className="num ml-auto text-[12px] text-muted">
                  {run.latency_ms != null && `${(run.latency_ms / 1000).toFixed(1)} s`}
                  {run.input_tokens != null && `, ${run.input_tokens.toLocaleString()} in`}
                  {run.output_tokens != null && ` / ${run.output_tokens.toLocaleString()} out`}
                </span>
              </div>
              {run.error && <p className="mt-1 text-[12.5px] text-bad">{run.error}</p>}
              {Array.isArray(run.validation?.errors) && (run.validation.errors as string[]).length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-[12.5px] text-review">
                  {(run.validation.errors as string[]).map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {r.llm_runs.length === 0 && <li className="px-5 py-4 text-muted">No AI calls for this requisition.</li>}
        </ul>
      )}
    </Panel>
  )
}

function TabBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className={cn('flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13.5px] transition-colors', on ? 'bg-black/[0.06] font-semibold' : 'text-muted hover:text-ink')}>
      {children}
    </button>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-6 w-80" />
      <Skeleton className="h-4 w-56" />
      <Skeleton className="h-16" />
      <div className="grid grid-cols-[3fr_2fr] gap-5">
        <div className="space-y-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-64" />
        </div>
        <Skeleton className="h-[480px]" />
      </div>
    </div>
  )
}
