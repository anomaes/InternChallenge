import { AlertTriangle, ChevronDown, CircleCheck, Info, OctagonAlert } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type IssueOut, type LineIn, type ReqDetail, type ReqSummary } from '@/api/client'
import { useMaster, useReqAction, useRequisitions } from '@/api/hooks'
import { cn, date, dateTime, money } from '@/lib/format'
import { StatePill } from './domain'
import { Button, Dialog, Input, Label, Panel, Select } from './ui'

type Act = ReturnType<typeof useActions>

function useActions(r: ReqDetail) {
  const id = r.id
  return {
    lines: useReqAction(id, (body: LineIn[]) => api.put<ReqDetail>(`/requisitions/${id}/lines`, body), 'Units set'),
    patch: useReqAction(id, (body: Record<string, unknown>) => api.patch<ReqDetail>(`/requisitions/${id}`, body), 'Saved'),
    confirm: useReqAction(id, (field: string) => api.post<ReqDetail>(`/requisitions/${id}/confirm`, { field }), 'Confirmed'),
    ack: useReqAction(id, (v: { issue: number; note?: string }) => api.post<ReqDetail>(`/requisitions/${id}/issues/${v.issue}/acknowledge`, { note: v.note }), 'Acknowledged'),
    override: useReqAction(id, (index: number) => api.post<ReqDetail>(`/requisitions/${id}/stated-totals/${index}/override`, {}), 'Decided: the lines are right'),
    assign: useReqAction(id, (v: { position: number; employee_id: string }) => api.post<ReqDetail>(`/requisitions/${id}/approvers`, v), 'Approver assigned'),
    dup: useReqAction(id, (action: string) => api.post<ReqDetail>(`/requisitions/${id}/duplicate`, { action }), (d) =>
      d.state === 'CLOSED_DUPLICATE' ? 'Closed' : 'Kept as a separate requisition',
    ),
    link: useReqAction(id, (public_id: string) => api.post<ReqDetail>(`/requisitions/${id}/link`, { public_id }), 'Linked'),
    order: useReqAction(id, () => api.post<ReqDetail>(`/requisitions/${id}/order`), (d) => (d.state === 'ORDERED' ? `Ordered as ${d.po_number}` : 'The order failed again')),
    createSupplier: useReqAction(id, async (body: Record<string, unknown>) => {
      await api.post(`/suppliers`, { ...body, requisition_id: id })
      return api.get<ReqDetail>(`/requisitions/${id}`)
    }, 'Supplier created and assigned'),
  }
}

const SEV: Record<string, { icon: ReactNode; ring: string; label: string }> = {
  blocking: { icon: <OctagonAlert size={15} className="text-review" />, ring: 'shadow-[inset_3px_0_0_var(--color-review)]', label: 'Blocks approval' },
  warning: { icon: <AlertTriangle size={15} className="text-muted" />, ring: '', label: 'Check' },
  info: { icon: <Info size={15} className="text-accent" />, ring: '', label: 'Note' },
}

export function IssuePanel({ r, onEditLines }: { r: ReqDetail; onEditLines: () => void }) {
  const act = useActions(r)
  const [showClosed, setShowClosed] = useState(false)
  const open = r.issues.filter((i) => i.status === 'open')
  const closed = r.issues.filter((i) => i.status !== 'open')
  const blocking = open.filter((i) => i.severity === 'blocking').length
  const editable = ['NEEDS_REVIEW', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED'].includes(r.state)
  const byPublicId = useByPublicId()

  return (
    <Panel>
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <h2 className="text-[15px] font-semibold">
          {open.length === 0 ? 'Nothing to resolve' : blocking ? `${blocking} to resolve before approval` : 'To check'}
        </h2>
        {closed.length > 0 && (
          <button onClick={() => setShowClosed((v) => !v)} className="flex items-center gap-1 text-[12.5px] text-muted hover:text-ink">
            {closed.length} resolved <ChevronDown size={13} className={cn('transition-transform', showClosed && 'rotate-180')} />
          </button>
        )}
      </div>
      {open.length === 0 && (
        <p className="flex items-center gap-2 px-5 pb-4 text-[13px] text-good">
          <CircleCheck size={15} /> Every value is established and nothing contradicts the document.
        </p>
      )}
      <ul className="divide-y divide-hairline border-t border-hairline">
        <AnimatePresence initial={false}>
          {open.map((issue) => (
            <motion.li key={issue.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }} className={cn('px-5 py-3.5', SEV[issue.severity].ring)}>
              <div className="flex gap-3">
                <span className="mt-0.5 shrink-0">{SEV[issue.severity].icon}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] leading-snug text-ink">{withLinks(issue.message, byPublicId)}</p>
                  {issue.blocks_order && issue.severity !== 'blocking' && <p className="mt-0.5 text-[12px] text-muted">Needed before the order can be placed.</p>}
                  {editable && (
                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      <IssueActions issue={issue} r={r} act={act} onEditLines={onEditLines} />
                    </div>
                  )}
                </div>
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      {showClosed && (
        <ul className="divide-y divide-hairline border-t border-hairline bg-sunken/60 text-[12.5px] text-muted">
          {closed.map((i) => (
            <li key={i.id} className="flex gap-3 px-5 py-2.5">
              <CircleCheck size={14} className="mt-0.5 shrink-0 text-good" />
              <div>
                <p className="line-through decoration-faint">{i.message}</p>
                <p className="mt-0.5">
                  {i.status === 'acknowledged' ? 'Acknowledged' : 'Resolved'} by {i.resolved_by === 'system' ? 'the system' : 'purchasing'} {dateTime(i.resolved_at)}
                  {i.resolution_note ? `: ${i.resolution_note}` : ''}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function IssueActions({ issue, r, act, onEditLines }: { issue: IssueOut; r: ReqDetail; act: Act; onEditLines: () => void }) {
  const master = useMaster()
  const ack = issue.acknowledgeable ? (
    <Button size="sm" variant="ghost" onClick={() => act.ack.mutate({ issue: issue.id })} loading={act.ack.isPending}>
      {issue.severity === 'info' ? 'Dismiss' : 'Acknowledge'}
    </Button>
  ) : null
  const code = issue.code
  const field = issue.field ?? ''
  const details = issue.details as Record<string, unknown>

  if (code.startsWith('supplier_') && code !== 'supplier_name_only') {
    return (
      <>
        <SupplierPicker r={r} act={act} />
        {code !== 'supplier_blocked' && <CreateSupplier r={r} act={act} />}
        {ack}
      </>
    )
  }
  if (code === 'supplier_name_only') {
    return (
      <>
        <Button size="sm" onClick={() => act.confirm.mutate('supplier')} loading={act.confirm.isPending}>
          Confirm {r.supplier?.name}
        </Button>
        <SupplierPicker r={r} act={act} label="Pick another" />
      </>
    )
  }
  if (code === 'cost_center_missing' || code === 'cost_center_unknown') {
    const sugg = (details.suggestions as { code: string; name: string; reason: string }[] | undefined) ?? r.cost_center_suggestions
    return (
      <>
        {sugg.slice(0, 3).map((s) => (
          <Button key={s.code} size="sm" title={s.reason} onClick={() => act.patch.mutate({ cost_center_code: s.code })}>
            Use {s.code} {s.name}
          </Button>
        ))}
        <Select className="h-7 w-auto text-[12.5px]" value="" onChange={(e) => e.target.value && act.patch.mutate({ cost_center_code: e.target.value })}>
          <option value="">Pick a cost center…</option>
          {master.data?.cost_centers.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} {c.name}
            </option>
          ))}
        </Select>
      </>
    )
  }
  if (code === 'currency_missing' || code === 'currency_unsupported') {
    const sugg = details.suggestion as string | undefined
    return (
      <>
        {sugg && (
          <Button size="sm" onClick={() => act.patch.mutate({ currency: sugg })}>
            Use {sugg}
          </Button>
        )}
        <Select className="h-7 w-auto text-[12.5px]" value="" onChange={(e) => e.target.value && act.patch.mutate({ currency: e.target.value })}>
          <option value="">Pick a currency…</option>
          {Object.keys(master.data?.fx_rates ?? {}).map((c) => (
            <option key={c}>{c}</option>
          ))}
        </Select>
      </>
    )
  }
  if (code === 'amount_conflict' && field.startsWith('stated_totals.')) {
    const idx = Number(details.index ?? field.split('.')[1])
    return (
      <>
        <Button size="sm" onClick={() => act.override.mutate(idx)} loading={act.override.isPending}>
          Lines are right: ignore {money(details.stated as string, r.currency)}
        </Button>
        <Button size="sm" variant="ghost" onClick={onEditLines}>
          Correct the lines
        </Button>
      </>
    )
  }
  if (code === 'unit_missing') {
    const positions = new Set((details.positions as number[] | undefined) ?? [])
    return (
      <>
        <Button
          size="sm"
          loading={act.lines.isPending}
          onClick={() => act.lines.mutate(r.lines.map((l) => ({ ...l, unit: positions.has(l.position) && !l.unit ? 'pcs' : l.unit })))}
        >
          Use “pcs” for {positions.size === 1 ? 'this line' : 'these lines'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onEditLines}>
          Edit line items
        </Button>
      </>
    )
  }
  if (['amount_conflict', 'unpriced_line', 'missing_quantity', 'invalid_quantity', 'no_line_items'].includes(code)) {
    return (
      <Button size="sm" onClick={onEditLines}>
        {code === 'no_line_items' ? 'Add line items' : 'Edit line items'}
      </Button>
    )
  }
  if (code === 'approximate_quantity') {
    return (
      <>
        <Button size="sm" onClick={() => act.confirm.mutate(field)}>
          Quantity is exact
        </Button>
        <Button size="sm" variant="ghost" onClick={onEditLines}>
          Change quantity
        </Button>
      </>
    )
  }
  if (code === 'unverified_value' || code === 'check_doubt') {
    return (
      <>
        <Button size="sm" onClick={() => act.confirm.mutate(field)} loading={act.confirm.isPending}>
          I checked it: confirm
        </Button>
        {field.startsWith('line.') && (
          <Button size="sm" variant="ghost" onClick={onEditLines}>
            Correct it
          </Button>
        )}
      </>
    )
  }
  if (code === 'delivery_date_suggested' || code === 'delivery_date_missing' || code === 'delivery_date_past') {
    return <DeliveryDate r={r} act={act} />
  }
  if (code === 'needs_manual_approver') {
    const position = Number(details.position ?? 1)
    return (
      <Select className="h-7 w-auto text-[12.5px]" value="" onChange={(e) => e.target.value && act.assign.mutate({ position, employee_id: e.target.value })}>
        <option value="">Assign an approver for step {position}…</option>
        {master.data?.employees
          .filter((e) => e.role !== 'requester_only' && e.id !== r.requester_id && !e.deputy_for)
          .map((e) => (
            <option key={e.id} value={e.id}>
              {e.name} ({e.role.replace(/_/g, ' ')})
            </option>
          ))}
      </Select>
    )
  }
  if (['suspected_duplicate', 'suspected_correction', 'possibly_related'].includes(code)) {
    return (
      <>
        {r.linked_to_id && (
          <Link to={`/r/${r.linked_to_id}`}>
            <Button size="sm" variant="ghost">
              Open {r.linked_to_public_id}
            </Button>
          </Link>
        )}
        <Button size="sm" onClick={() => act.dup.mutate('apply_correction')} loading={act.dup.isPending}>
          Apply as correction to {r.linked_to_public_id}
        </Button>
        <Button size="sm" onClick={() => act.dup.mutate('close')}>
          Close as duplicate
        </Button>
        <Button size="sm" variant="ghost" onClick={() => act.dup.mutate('keep')}>
          Keep both
        </Button>
      </>
    )
  }
  if (code === 'unlinked_correction' || code === 'unlinked_repeat') {
    const cands = (details.candidates as string[] | undefined) ?? []
    return (
      <>
        {cands.length > 0 && <LinkCandidates candidates={cands} act={act} verb={code === 'unlinked_correction' ? 'It corrects this' : 'It repeats this'} />}
        <LinkTo act={act} />
        {ack}
      </>
    )
  }
  if (code === 'requester_unknown' || code === 'on_behalf_of' || code === 'requester_from_thread') {
    return (
      <>
        <Select className="h-7 w-auto text-[12.5px]" value="" onChange={(e) => e.target.value && act.patch.mutate({ requester_id: e.target.value })}>
          <option value="">{code === 'requester_unknown' ? 'Pick the requester…' : 'Change the requester…'}</option>
          {master.data?.employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </Select>
        {ack}
      </>
    )
  }
  if (code === 'order_failed') {
    return (
      <Button size="sm" variant="primary" onClick={() => act.order.mutate(undefined)} loading={act.order.isPending}>
        Retry the order
      </Button>
    )
  }
  return ack
}

function SupplierPicker({ r, act, label = 'Pick the supplier' }: { r: ReqDetail; act: Act; label?: string }) {
  const master = useMaster()
  const candidates = new Set(r.supplier_candidates.map((c) => c.id))
  return (
    <Select className="h-7 w-auto max-w-[260px] text-[12.5px]" value="" onChange={(e) => e.target.value && act.patch.mutate({ supplier_id: e.target.value })}>
      <option value="">{label}…</option>
      {r.supplier_candidates.length > 0 && (
        <optgroup label="Likely">
          {r.supplier_candidates.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.id}){c.via ? `, by ${c.via === 'vat' ? 'VAT ID' : 'name'}` : ''}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label="All suppliers">
        {master.data?.suppliers
          .filter((s) => !candidates.has(s.id))
          .map((s) => (
            <option key={s.id} value={s.id} disabled={s.status === 'blocked'}>
              {s.name}
              {s.status === 'blocked' ? ' (blocked)' : ''}
            </option>
          ))}
      </optgroup>
    </Select>
  )
}

function CreateSupplier({ r, act }: { r: ReqDetail; act: Act }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: r.supplier_name_doc ?? '', vat_id: r.supplier_vat_doc ?? '', country: 'CH', default_currency: r.currency ?? 'CHF' })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value })
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        Create supplier
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Create a supplier"
        description="Prefilled from the document. Check the details against the quote or the supplier's register entry before saving: a new supplier is a fraud risk."
      >
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            act.createSupplier.mutate(form, { onSuccess: () => setOpen(false) })
          }}
        >
          <div>
            <Label htmlFor="sn">Legal name</Label>
            <Input id="sn" value={form.name} onChange={set('name')} required />
          </div>
          <div>
            <Label htmlFor="sv" hint="optional">
              VAT / UID
            </Label>
            <Input id="sv" value={form.vat_id} onChange={set('vat_id')} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="sc">Country</Label>
              <Input id="sc" value={form.country} onChange={set('country')} maxLength={2} />
            </div>
            <div>
              <Label htmlFor="scur">Currency</Label>
              <Select id="scur" value={form.default_currency} onChange={set('default_currency')}>
                {['CHF', 'EUR', 'USD', 'GBP'].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </Select>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={act.createSupplier.isPending}>
              Create and assign
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  )
}

function DeliveryDate({ r, act }: { r: ReqDetail; act: Act }) {
  const [value, setValue] = useState(r.delivery_date ?? r.delivery_date_suggested ?? '')
  return (
    <>
      {r.delivery_date_suggested && !r.delivery_date && (
        <Button size="sm" onClick={() => act.confirm.mutate('delivery_date')} loading={act.confirm.isPending}>
          Use {date(r.delivery_date_suggested)}
        </Button>
      )}
      <form
        className="flex items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          if (value) act.patch.mutate({ delivery_date: value })
        }}
      >
        <Input type="date" value={value} onChange={(e) => setValue(e.target.value)} className="h-7 w-[150px] text-[12.5px]" aria-label="Delivery date" />
        <Button size="sm" type="submit" variant="ghost" disabled={!value}>
          Set date
        </Button>
      </form>
    </>
  )
}

function useByPublicId() {
  const { data } = useRequisitions()
  return useMemo(() => new Map((data ?? []).map((x) => [x.public_id, x])), [data])
}

/** Turn requisition IDs in a message into links, so they can be looked at before deciding. */
function withLinks(message: string, byPublicId: Map<string, ReqSummary>): ReactNode {
  return message.split(/(REQ-\d{4,})/).map((part, i) => {
    const target = i % 2 ? byPublicId.get(part) : undefined
    return target ? (
      <Link key={i} to={`/r/${target.id}`} className="num text-accent hover:underline">
        {part}
      </Link>
    ) : (
      part
    )
  })
}

/** The earlier requests this one might belong to, with enough to tell them apart. */
function LinkCandidates({ candidates, act, verb }: { candidates: string[]; act: Act; verb: string }) {
  const byPublicId = useByPublicId()
  return (
    <ul className="w-full divide-y divide-hairline overflow-hidden rounded-lg text-[12.5px] shadow-[0_0_0_0.5px_var(--color-hairline-strong)]">
      {candidates.map((c) => {
        const x = byPublicId.get(c)
        return (
          <li key={c} className="flex items-center gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate">
                {x ? (
                  <Link to={`/r/${x.id}`} className="num font-medium text-accent hover:underline">
                    {c}
                  </Link>
                ) : (
                  <span className="num font-medium">{c}</span>
                )}
                {x?.title && <span className="text-ink"> {x.title}</span>}
              </p>
              {x && (
                <p className="truncate text-[12px] text-muted">
                  {[x.supplier_name ?? x.supplier_name_doc, date(x.sent_at ?? x.received_at)].filter(Boolean).join(', ')}
                  {x.po_total && <span className="num">, {money(x.po_total, x.currency)}</span>}
                </p>
              )}
            </div>
            {x && <StatePill state={x.state} stage={x.stage} />}
            <Button size="sm" onClick={() => act.link.mutate(c)} loading={act.link.isPending && act.link.variables === c}>
              {verb}
            </Button>
          </li>
        )
      })}
    </ul>
  )
}

function LinkTo({ act }: { act: Act }) {
  const [v, setV] = useState('')
  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        if (v.trim()) act.link.mutate(v.trim())
      }}
    >
      <Input value={v} onChange={(e) => setV(e.target.value)} placeholder="REQ-0001" className="h-7 w-[110px] text-[12.5px]" aria-label="Requisition ID" />
      <Button size="sm" variant="ghost" type="submit" disabled={!v.trim()}>
        Link
      </Button>
    </form>
  )
}
