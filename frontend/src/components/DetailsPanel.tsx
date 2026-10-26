import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { api, type LineIn, type ReqDetail } from '@/api/client'
import { useMaster, useReqAction } from '@/api/hooks'
import { cn, date, money, qty } from '@/lib/format'
import { ProvChip } from './domain'
import { Badge, Button, Input, Panel, Select, Tip } from './ui'

const EDITABLE = ['NEEDS_REVIEW', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED']

// ---------------------------------------------------------------- header fields

function Row({ label, value, chip, editor, canEdit }: { label: string; value: ReactNode; chip?: ReactNode; editor?: (done: () => void) => ReactNode; canEdit?: boolean }) {
  const [editing, setEditing] = useState(false)
  return (
    <div className="grid grid-cols-[132px_minmax(0,1fr)] items-start gap-3 border-b border-hairline px-5 py-2.5 last:border-0">
      <dt className="pt-[3px] text-[13px] text-muted">{label}</dt>
      <dd className="min-w-0">
        {editing && editor ? (
          editor(() => setEditing(false))
        ) : (
          <div className="group flex min-h-[26px] flex-wrap items-center gap-x-2 gap-y-1">
            <span className="min-w-0 text-[13.5px]">{value}</span>
            {chip}
            {canEdit && editor && (
              <button onClick={() => setEditing(true)} className="ml-auto rounded-md p-1 text-faint opacity-0 transition-opacity group-hover:opacity-100 hover:bg-black/5 hover:text-ink focus-visible:opacity-100" aria-label={`Edit ${label}`}>
                <Pencil size={13} />
              </button>
            )}
          </div>
        )}
      </dd>
    </div>
  )
}

function InlineSelect({ value, options, onSave, onCancel, pending }: { value: string; options: { value: string; label: string; disabled?: boolean }[]; onSave: (v: string) => void; onCancel: () => void; pending?: boolean }) {
  const [v, setV] = useState(value)
  return (
    <div className="flex items-center gap-1.5">
      <Select autoFocus value={v} onChange={(e) => setV(e.target.value)} className="h-7.5 text-[13px]">
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </Select>
      <Button size="sm" variant="primary" onClick={() => onSave(v)} loading={pending} aria-label="Save">
        <Check size={13} />
      </Button>
      <Button size="sm" variant="ghost" onClick={onCancel} aria-label="Cancel">
        <X size={13} />
      </Button>
    </div>
  )
}

export function FieldsPanel({ r, onEvidence }: { r: ReqDetail; onEvidence: (t: string) => void }) {
  const master = useMaster()
  const patch = useReqAction(r.id, (body: Record<string, unknown>) => api.patch<ReqDetail>(`/requisitions/${r.id}`, body), 'Saved')
  const confirm = useReqAction(r.id, (field: string) => api.post<ReqDetail>(`/requisitions/${r.id}/confirm`, { field }), 'Confirmed')
  const canEdit = EDITABLE.includes(r.state)
  const p = r.provenance
  const save = (field: string, done: () => void) => (v: string) =>
    patch.mutate(v ? { [field]: v } : { clear: [field] }, { onSuccess: done })

  const md = master.data
  return (
    <Panel>
      <div className="px-5 pt-4 pb-2">
        <h2 className="text-[15px] font-semibold">Request</h2>
      </div>
      <dl className="border-t border-hairline">
        <Row
          label="Requester"
          canEdit={canEdit}
          value={r.requester_name ?? <span className="text-bad">Unknown</span>}
          chip={
            <>
              <ProvChip p={p.requester} fallback={r.requester_id ? 'from_document' : 'missing'} onEvidence={onEvidence} />
              {r.requester_source === 'thread' && <Badge tone="accent">derived from thread</Badge>}
            </>
          }
          editor={(done) => (
            <InlineSelect value={r.requester_id ?? ''} pending={patch.isPending} onCancel={done} onSave={save('requester_id', done)} options={(md?.employees ?? []).map((e) => ({ value: e.id, label: e.name }))} />
          )}
        />
        <Row
          label="Supplier"
          canEdit={canEdit}
          value={
            r.supplier ? (
              <span>
                {r.supplier.name} <span className="text-muted">{r.supplier.id}</span>
                {r.supplier.status === 'blocked' && (
                  <Badge tone="bad" className="ml-1.5">
                    blocked
                  </Badge>
                )}
                {(r.supplier_name_doc && r.supplier_name_doc !== r.supplier.name) || r.supplier_vat_doc ? (
                  <span className="block text-[12px] text-muted">
                    Document says {r.supplier_name_doc ?? '—'}
                    {r.supplier_vat_doc && <>, VAT {r.supplier_vat_doc}</>}
                  </span>
                ) : null}
              </span>
            ) : (
              <span>
                <span className="text-bad">Not matched</span>
                {r.supplier_name_doc && <span className="block text-[12px] text-muted">Document says {r.supplier_name_doc}{r.supplier_vat_doc && <>, VAT {r.supplier_vat_doc}</>}</span>}
              </span>
            )
          }
          chip={<ProvChip p={p.supplier} fallback="missing" onEvidence={onEvidence} />}
          editor={(done) => (
            <InlineSelect
              value={r.supplier_id ?? ''}
              pending={patch.isPending}
              onCancel={done}
              onSave={save('supplier_id', done)}
              options={(md?.suppliers ?? []).map((s) => ({ value: s.id, label: `${s.name} (${s.id})${s.status === 'blocked' ? ', blocked' : ''}` }))}
            />
          )}
        />
        <Row
          label="Cost center"
          canEdit={canEdit}
          value={
            r.cost_center ? (
              <span>
                {r.cost_center.code} {r.cost_center.name}
                <span className="block text-[12px] text-muted">
                  Owner {r.cost_center.owner_name}, {r.cost_center.department_name} headed by {r.cost_center.head_name}
                </span>
              </span>
            ) : (
              <span>
                <span className="text-bad">{r.cost_center_doc ? `${r.cost_center_doc} is unknown` : 'Not stated'}</span>
                {r.cost_center_text && <span className="block text-[12px] text-muted">Email says “{r.cost_center_text}”</span>}
              </span>
            )
          }
          chip={<ProvChip p={p.cost_center} fallback="missing" onEvidence={onEvidence} />}
          editor={(done) => (
            <InlineSelect value={r.cost_center_code ?? ''} pending={patch.isPending} onCancel={done} onSave={save('cost_center_code', done)} options={(md?.cost_centers ?? []).map((c) => ({ value: c.code, label: `${c.code} ${c.name}` }))} />
          )}
        />
        <Row
          label="Currency"
          canEdit={canEdit}
          value={r.currency ?? <span className="text-bad">Not stated</span>}
          chip={r.currency ? <ProvChip p={p.currency} onEvidence={onEvidence} /> : undefined}
          editor={(done) => (
            <InlineSelect value={r.currency ?? ''} pending={patch.isPending} onCancel={done} onSave={save('currency', done)} options={Object.keys(md?.fx_rates ?? {}).map((c) => ({ value: c, label: c }))} />
          )}
        />
        <Row
          label="Delivery date"
          canEdit={canEdit}
          value={
            r.delivery_date ? (
              date(r.delivery_date)
            ) : r.delivery_date_suggested ? (
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-muted">Suggested {date(r.delivery_date_suggested)}</span>
                {canEdit && (
                  <Button size="sm" onClick={() => confirm.mutate('delivery_date')} loading={confirm.isPending}>
                    Use it
                  </Button>
                )}
              </span>
            ) : (
              <span className="text-muted">Not stated</span>
            )
          }
          chip={
            <>
              <ProvChip p={p.delivery_date} fallback="missing" onEvidence={onEvidence} />
              {r.delivery_date_text && <span className="w-full text-[12px] text-muted">“{r.delivery_date_text}”</span>}
            </>
          }
          editor={(done) => <DateEditor value={r.delivery_date ?? r.delivery_date_suggested ?? ''} pending={patch.isPending} onCancel={done} onSave={save('delivery_date', done)} />}
        />
        <Row
          label="GL account"
          canEdit={canEdit}
          value={
            r.gl_account ? (
              `${r.gl_account} ${r.gl_account_name}`
            ) : r.gl_account_suggested ? (
              <span className="flex flex-wrap items-center gap-2">
                <Tip content={r.gl_account_reason ?? 'AI suggestion from the item descriptions'}>
                  <span className="text-muted">
                    Suggested {r.gl_account_suggested} {r.gl_account_suggested_name}
                  </span>
                </Tip>
                {canEdit && (
                  <Button size="sm" onClick={() => confirm.mutate('gl_account')} loading={confirm.isPending}>
                    Confirm
                  </Button>
                )}
              </span>
            ) : (
              <span className="text-muted">Optional</span>
            )
          }
          chip={r.gl_account || r.gl_account_suggested ? <ProvChip p={p.gl_account} fallback="suggested" /> : undefined}
          editor={(done) => (
            <InlineSelect value={r.gl_account ?? r.gl_account_suggested ?? ''} pending={patch.isPending} onCancel={done} onSave={save('gl_account', done)} options={(md?.gl_accounts ?? []).map((g) => ({ value: g.code, label: `${g.code} ${g.name}` }))} />
          )}
        />
        {(r.quote_reference || r.quote_valid_until) && (
          <Row
            label="Quote"
            value={
              <span>
                {r.quote_reference ?? 'No reference'}
                {r.quote_date && <span className="text-muted"> of {date(r.quote_date)}</span>}
                {r.quote_valid_until && <span className={cn('block text-[12px]', r.issues.some((i) => i.code === 'quote_expired' && i.status !== 'resolved') ? 'text-review' : 'text-muted')}>Valid until {date(r.quote_valid_until)}</span>}
              </span>
            }
          />
        )}
        {r.prior_approval_claim && <Row label="Claimed approval" value={<span className="text-review">“{r.prior_approval_claim}”</span>} />}
      </dl>
    </Panel>
  )
}

function DateEditor({ value, onSave, onCancel, pending }: { value: string; onSave: (v: string) => void; onCancel: () => void; pending?: boolean }) {
  const [v, setV] = useState(value)
  return (
    <div className="flex items-center gap-1.5">
      <Input autoFocus type="date" value={v} onChange={(e) => setV(e.target.value)} className="h-7.5 w-[160px] text-[13px]" />
      <Button size="sm" variant="primary" onClick={() => onSave(v)} loading={pending} aria-label="Save">
        <Check size={13} />
      </Button>
      <Button size="sm" variant="ghost" onClick={onCancel} aria-label="Cancel">
        <X size={13} />
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------- line items

type Draft = LineIn & { key: string }

export function LinesPanel({ r, editing, setEditing, onEvidence }: { r: ReqDetail; editing: boolean; setEditing: (v: boolean) => void; onEvidence: (t: string) => void }) {
  const save = useReqAction(r.id, (body: LineIn[]) => api.put<ReqDetail>(`/requisitions/${r.id}/lines`, body), 'Line items saved')
  const [draft, setDraft] = useState<Draft[]>([])
  const canEdit = EDITABLE.includes(r.state)

  const start = () => {
    setDraft(
      r.lines.map((l) => ({
        key: String(l.id),
        id: l.id,
        kind: l.kind,
        description: l.description,
        item_code: l.item_code,
        quantity: l.quantity,
        unit: l.unit,
        unit_price: l.unit_price,
        price_basis: l.price_basis,
      })),
    )
    if (r.lines.length === 0) setDraft([{ key: 'n0', kind: 'item', description: '', quantity: null, unit: 'pcs', unit_price: null }])
    setEditing(true)
  }
  // Opened from an issue ("Edit line items"): load the current lines into the draft.
  useEffect(() => {
    if (editing && draft.length === 0) start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing])

  const set = (i: number, k: keyof LineIn, v: string) => setDraft((d) => d.map((x, j) => (j === i ? { ...x, [k]: v === '' ? null : v } : x)))

  if (editing) {
    return (
      <Panel id="line-editor" className="scroll-mt-4 ring-2 ring-accent-soft">
        <div className="flex items-center justify-between px-5 pt-4 pb-3">
          <h2 className="text-[15px] font-semibold">Edit line items</h2>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => (setEditing(false), setDraft([]))}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  draft.filter((d) => d.description.trim()).map(({ key: _k, ...rest }) => rest),
                  { onSuccess: () => (setEditing(false), setDraft([])) },
                )
              }
            >
              Save lines
            </Button>
          </div>
        </div>
        <div className="overflow-x-auto border-t border-hairline">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead className="text-left text-[12px] text-muted">
              <tr>
                <th className="py-2 pl-5 font-medium">Kind</th>
                <th className="px-2 font-medium">Description</th>
                <th className="px-2 font-medium">Item code</th>
                <th className="px-2 text-right font-medium">Qty</th>
                <th className="px-2 font-medium">Unit</th>
                <th className="px-2 text-right font-medium">Unit price</th>
                <th className="px-2 text-right font-medium">Per</th>
                <th className="pr-5" />
              </tr>
            </thead>
            <tbody>
              {draft.map((d, i) => (
                <tr key={d.key} className="border-t border-hairline">
                  <td className="py-1.5 pl-5">
                    <Select value={d.kind ?? 'item'} onChange={(e) => set(i, 'kind', e.target.value)} className="h-7.5 w-[104px] text-[12.5px]">
                      <option value="item">Item</option>
                      <option value="freight">Freight</option>
                      <option value="surcharge">Surcharge</option>
                      <option value="discount">Discount</option>
                    </Select>
                  </td>
                  <td className="px-2">
                    <Input value={d.description} onChange={(e) => set(i, 'description', e.target.value)} className="h-7.5 text-[12.5px]" aria-label="Description" />
                  </td>
                  <td className="px-2">
                    <Input value={d.item_code ?? ''} onChange={(e) => set(i, 'item_code', e.target.value)} className="h-7.5 w-[110px] text-[12.5px]" aria-label="Item code" />
                  </td>
                  <td className="px-2">
                    <Input inputMode="decimal" value={d.quantity ?? ''} onChange={(e) => set(i, 'quantity', e.target.value)} className="num h-7.5 w-[84px] text-right text-[12.5px]" aria-label="Quantity" />
                  </td>
                  <td className="px-2">
                    <Input value={d.unit ?? ''} onChange={(e) => set(i, 'unit', e.target.value)} className="h-7.5 w-[64px] text-[12.5px]" aria-label="Unit" />
                  </td>
                  <td className="px-2">
                    <Input inputMode="decimal" value={d.unit_price ?? ''} onChange={(e) => set(i, 'unit_price', e.target.value)} className="num h-7.5 w-[104px] text-right text-[12.5px]" aria-label="Unit price" />
                  </td>
                  <td className="px-2">
                    <Input inputMode="decimal" value={d.price_basis ?? ''} placeholder="1" onChange={(e) => set(i, 'price_basis', e.target.value)} className="num h-7.5 w-[56px] text-right text-[12.5px]" aria-label="Price per units" />
                  </td>
                  <td className="pr-5 text-right">
                    <button onClick={() => setDraft((x) => x.filter((_, j) => j !== i))} className="rounded-md p-1.5 text-faint hover:bg-bad-soft hover:text-bad" aria-label="Remove line">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-5 py-3">
          <Button size="sm" variant="ghost" onClick={() => setDraft((d) => [...d, { key: `n${Date.now()}`, kind: 'item', description: '', quantity: null, unit: 'pcs', unit_price: null }])}>
            <Plus size={13} /> Add line
          </Button>
        </div>
      </Panel>
    )
  }

  return (
    <Panel>
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <h2 className="text-[15px] font-semibold">
          Line items <span className="num ml-1 font-normal text-muted">{r.lines.length}</span>
        </h2>
        {canEdit && (
          <Button size="sm" variant="ghost" onClick={start}>
            <Pencil size={13} /> Edit
          </Button>
        )}
      </div>
      {r.lines.length === 0 ? (
        <p className="border-t border-hairline px-5 py-6 text-center text-[13px] text-muted">No line items were found in the email or its attachments.</p>
      ) : (
        <div className="overflow-x-auto border-t border-hairline">
          <table className="w-full min-w-[640px] text-[13px]">
            <thead className="text-left text-[12px] text-muted">
              <tr>
                <th className="py-2 pl-5 font-medium">Item</th>
                <th className="px-3 text-right font-medium">Quantity</th>
                <th className="px-3 text-right font-medium">Unit price</th>
                <th className="px-3 pr-5 text-right font-medium">Line value</th>
              </tr>
            </thead>
            <tbody>
              {r.lines.map((l) => {
                const lp = l.provenance
                const qtyP = lp.quantity ?? lp.line
                const priceP = lp.unit_price ?? lp.line
                const doubt = (x?: { status?: string | null; source?: string | null; grounded?: boolean | null; check?: number | null }) =>
                  !!x && x.source !== 'clerk' && (x.grounded === false || (x.check != null && x.check < 0.8))
                return (
                  <tr key={l.id} className="border-t border-hairline align-top">
                    <td className="py-2.5 pl-5">
                      <button type="button" onClick={() => l.source_quote && onEvidence(l.source_quote)} className="text-left hover:text-accent">
                        {l.description}
                      </button>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                        {l.kind !== 'item' && <Badge tone={l.kind === 'discount' ? 'good' : 'neutral'}>{l.kind}</Badge>}
                        {l.item_code && <span>{l.item_code}</span>}
                        {(qtyP || priceP) && <ProvChip compact p={doubt(qtyP) ? qtyP : doubt(priceP) ? priceP : (qtyP ?? priceP)} onEvidence={onEvidence} />}
                      </div>
                    </td>
                    <td className={cn('num px-3 py-2.5 text-right whitespace-nowrap', doubt(lp.quantity) && 'text-review')}>
                      {l.quantity_approximate && <span className="text-review">about </span>}
                      {qty(l.quantity)} <span className="text-muted">{l.unit}</span>
                    </td>
                    <td className={cn('num px-3 py-2.5 text-right whitespace-nowrap', l.unit_price == null && 'text-bad', doubt(lp.unit_price) && 'text-review')}>
                      {l.unit_price == null ? 'no price' : money(l.unit_price)}
                      {l.price_basis && <span className="block text-[11.5px] text-muted">per {qty(l.price_basis)}</span>}
                    </td>
                    <td className="num px-3 py-2.5 pr-5 text-right whitespace-nowrap">
                      {money(l.line_value)}
                      {l.stated_line_total != null && l.line_value != null && Math.abs(Number(l.stated_line_total) - Math.abs(Number(l.line_value))) > 0.015 && (
                        <span className="block text-[11.5px] text-bad">document says {money(l.stated_line_total)}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------- amounts

export function AmountsPanel({ r }: { r: ReqDetail }) {
  const master = useMaster()
  const band = master.data?.approval_bands.find((b) => b.position === r.band_position)
  const conflicts = new Set(r.issues.filter((i) => i.status === 'open' && i.code === 'amount_conflict').map((i) => i.field))
  const hasDiscount = r.lines.some((l) => l.kind === 'discount')
  const hasFreight = r.lines.some((l) => l.kind === 'freight' || l.kind === 'surcharge')
  return (
    <Panel>
      <div className="px-5 pt-4 pb-3">
        <h2 className="text-[15px] font-semibold">Amounts</h2>
      </div>
      <dl className="space-y-2 border-t border-hairline px-5 py-3.5 text-[13px]">
        <AmountRow label="Order total, net" value={money(r.po_total, r.currency)} hint="All lines, excl. VAT. Sent to the ERP." />
        <AmountRow
          label="Amount for approval"
          value={money(r.approval_amount, r.currency)}
          hint={hasDiscount ? 'Discounts are not subtracted: a discount never lowers the approval band.' : hasFreight ? 'Freight and surcharges count.' : 'Excl. VAT.'}
        />
        {r.currency && r.currency !== 'CHF' && r.fx_rate && <AmountRow label={`In CHF at ${Number(r.fx_rate).toFixed(2)}`} value={money(r.approval_amount_chf, 'CHF')} strong />}
        {r.currency === 'CHF' && <AmountRow label="In CHF" value={money(r.approval_amount_chf, 'CHF')} strong />}
        {band && (
          <div className="rounded-lg bg-sunken px-3 py-2 text-[12.5px] text-ink-2 shadow-[0_0_0_0.5px_var(--color-hairline)]">
            Band {band.position}, CHF {money(band.lower, null, { decimals: false })} to {band.upper ? money(band.upper, null, { decimals: false }) : 'no limit'}: {band.role_labels.join(', then ')}
          </div>
        )}
        {r.vat_amount != null && <AmountRow label={`VAT${r.vat_rate ? ` ${Number(r.vat_rate)}%` : ''}`} value={money(r.vat_amount, r.currency)} hint="Recorded, not used for routing." />}
      </dl>
      {r.stated_totals.length > 0 && (
        <div className="border-t border-hairline px-5 py-3.5">
          <p className="mb-2 text-[12.5px] text-muted">Figures printed in the document</p>
          <ul className="space-y-1.5 text-[13px]">
            {r.stated_totals.map((t, i) => {
              const bad = conflicts.has(`stated_totals.${i}`)
              return (
                <li key={i} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-ink-2">
                    {t.label}
                    {t.approximate && <span className="text-muted"> (approximate)</span>}
                  </span>
                  <span className={cn('num', bad && 'text-bad', t.overridden && 'text-faint line-through')}>{money(t.amount, r.currency)}</span>
                  {t.overridden ? <Badge>ignored</Badge> : bad ? <Badge tone="bad">contradicts the lines</Badge> : t.approximate ? <Badge>not used</Badge> : <Badge tone="good">consistent</Badge>}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </Panel>
  )
}

function AmountRow({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-ink-2">{label}</dt>
        <dd className={cn('num', strong && 'text-[15px] font-semibold')}>{value}</dd>
      </div>
      {hint && <p className="text-[12px] text-muted">{hint}</p>}
    </div>
  )
}
