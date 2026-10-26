import { ArrowDown, ArrowUp, Link2, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type { ReqSummary } from '@/api/client'
import { useRequisitions } from '@/api/hooks'
import { RouteMini, StatePill } from '@/components/domain'
import { Page, PageHeader } from '@/components/Layout'
import { Badge, Empty, Input, Kbd, Panel, Skeleton, Tip } from '@/components/ui'
import { ago, cn, money } from '@/lib/format'

const VIEWS: { key: string; label: string; match: (r: ReqSummary) => boolean }[] = [
  { key: 'all', label: 'All', match: () => true },
  { key: 'review', label: 'Needs review', match: (r) => r.state === 'NEEDS_REVIEW' },
  { key: 'approval', label: 'Waiting for approvers', match: (r) => r.state === 'PENDING_APPROVAL' },
  { key: 'order', label: 'Approved', match: (r) => r.state === 'APPROVED' },
  { key: 'done', label: 'Ordered', match: (r) => r.state === 'ORDERED' },
  { key: 'closed', label: 'Rejected and closed', match: (r) => r.state === 'REJECTED' || r.state === 'CLOSED_DUPLICATE' },
  { key: 'processing', label: 'Processing', match: (r) => ['INBOX', 'PROCESSING', 'EXTRACTED'].includes(r.state) },
]

type SortKey = 'id' | 'received' | 'requester' | 'supplier' | 'amount' | 'state'
const SORTS: Record<SortKey, (r: ReqSummary) => string | number> = {
  id: (r) => r.id,
  received: (r) => r.sent_at ?? r.received_at,
  requester: (r) => r.requester_name ?? '',
  supplier: (r) => r.supplier_name ?? r.supplier_name_doc ?? '',
  amount: (r) => Number(r.approval_amount_chf ?? -1),
  state: (r) => r.state,
}

const SUPPLIER_TONE: Record<string, { label: string; tone: 'good' | 'neutral' | 'review' | 'bad' }> = {
  confirmed: { label: 'VAT match', tone: 'good' },
  from_document: { label: 'name only', tone: 'neutral' },
  unverified: { label: 'unverified', tone: 'review' },
  conflict: { label: 'conflict', tone: 'bad' },
  missing: { label: 'not found', tone: 'bad' },
}

// Survives the trip to a requisition and back, so returning lands on the same row.
let lastOpened: number | null = null

export function RequisitionsPage() {
  const { data, isPending } = useRequisitions()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'all'
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'id', dir: -1 })
  const [cursor, setCursor] = useState(0)
  const navigate = useNavigate()
  const searchRef = useRef<HTMLInputElement>(null)

  const open = useCallback(
    (id: number) => {
      lastOpened = id
      navigate(`/r/${id}`)
    },
    [navigate],
  )

  const counts = useMemo(() => Object.fromEntries(VIEWS.map((v) => [v.key, (data ?? []).filter(v.match).length])), [data])
  const rows = useMemo(() => {
    const match = VIEWS.find((v) => v.key === view)?.match ?? (() => true)
    const needle = q.trim().toLowerCase()
    const out = (data ?? []).filter(match).filter((r) => {
      if (!needle) return true
      return [r.public_id, r.title, r.requester_name, r.supplier_name, r.supplier_name_doc, r.cost_center_code, r.source_name]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(needle))
    })
    const f = SORTS[sort.key]
    return out.sort((a, b) => (f(a) > f(b) ? 1 : f(a) < f(b) ? -1 : 0) * sort.dir)
  }, [data, view, q, sort])

  useEffect(() => {
    if (lastOpened === null || !data) return
    const i = rows.findIndex((r) => r.id === lastOpened)
    if (i >= 0) setCursor(i)
    lastOpened = null
  }, [data, rows])

  // Keyboard: K/J to move down/up, Enter to open, / to search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest('input, textarea, select, [cmdk-root]')
      if (typing || e.metaKey || e.ctrlKey) return
      if (e.key === 'k' || e.key === 'ArrowDown') {
        e.preventDefault()
        setCursor((c) => Math.min(rows.length - 1, c + 1))
      } else if (e.key === 'j' || e.key === 'ArrowUp') {
        e.preventDefault()
        setCursor((c) => Math.max(0, c - 1))
      } else if (e.key === 'Enter' && rows[cursor]) {
        open(rows[cursor].id)
      } else if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rows, cursor, open])

  useEffect(() => {
    document.querySelector(`[data-row="${cursor}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  const th = (key: SortKey, label: string, className?: string) => (
    <th className={cn('px-3 py-2.5 font-medium', className)}>
      <button
        className="inline-flex items-center gap-1 hover:text-ink"
        onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === 'amount' || key === 'id' ? -1 : 1 }))}
      >
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </th>
  )

  return (
    <>
      <PageHeader
        title="Requisitions"
        sub={
          <span className="flex items-center gap-1.5">
            <Kbd>K</Kbd>
            <Kbd>J</Kbd> to move down and up, <Kbd>↵</Kbd> to open, <Kbd>/</Kbd> to search
          </span>
        }
        actions={
          <div className="relative w-64">
            <Search size={14} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-faint" />
            <Input ref={searchRef} value={q} onChange={(e) => (setQ(e.target.value), setCursor(0))} placeholder="Search" className="pl-8" />
          </div>
        }
      >
        <div className="mx-auto flex max-w-[1500px] gap-1 overflow-x-auto px-4 pb-2.5 sm:px-8">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              onClick={() => (setParams(v.key === 'all' ? {} : { view: v.key }), setCursor(0))}
              className={cn(
                'flex h-7 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors',
                view === v.key ? 'bg-ink text-white' : 'text-ink-2 hover:bg-black/5',
              )}
            >
              {v.label}
              <span className={cn('num', view === v.key ? 'text-white/60' : 'text-faint')}>{counts[v.key] ?? 0}</span>
            </button>
          ))}
        </div>
      </PageHeader>
      <Page>
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[1040px] text-left text-[13px]">
            <thead className="border-b border-hairline text-[12px] text-muted">
              <tr>
                {th('id', 'ID', 'pl-5')}
                {th('requester', 'Request')}
                {th('supplier', 'Supplier')}
                {th('amount', 'Amount', 'text-right')}
                {th('state', 'State')}
                <th className="px-3 py-2.5 font-medium">Now with</th>
                <th className="px-3 py-2.5 pr-5 font-medium">Issues</th>
              </tr>
            </thead>
            <tbody>
              {isPending &&
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-5 py-3">
                      <Skeleton className="h-5" />
                    </td>
                  </tr>
                ))}
              {rows.map((r, i) => {
                const st = r.supplier_status ? SUPPLIER_TONE[r.supplier_status] : undefined
                return (
                  <tr
                    key={r.id}
                    data-row={i}
                    onClick={() => open(r.id)}
                    onMouseMove={() => cursor !== i && setCursor(i)}
                    className={cn('h-11 cursor-default border-b border-hairline last:border-0', i === cursor && 'bg-accent-soft/60')}
                  >
                    <td className="num py-2 pr-3 pl-5 whitespace-nowrap text-muted">
                      <span className="flex items-center gap-1">
                        {r.public_id}
                        {r.linked_to_public_id && (
                          <Tip content={`Linked to ${r.linked_to_public_id} (${r.link_type})`}>
                            <Link2 size={12} className="text-accent" />
                          </Tip>
                        )}
                      </span>
                      <span className="block text-[11.5px] text-faint">{ago(r.sent_at ?? r.received_at)}</span>
                    </td>
                    <td className="max-w-[260px] px-3">
                      <p className="truncate font-medium">{r.title || r.source_name}</p>
                      <p className="truncate text-[12px] text-muted">{r.requester_name ?? <span className="text-bad">Unknown requester</span>}</p>
                    </td>
                    <td className="max-w-[220px] px-3">
                      <div className="flex items-center gap-1.5">
                        <span className={cn('truncate', !r.supplier_name && 'text-muted')}>{r.supplier_name ?? r.supplier_name_doc ?? '—'}</span>
                        {r.supplier_blocked ? <Badge tone="bad">blocked</Badge> : st && (r.supplier_name_doc || r.supplier_name) && <Badge tone={st.tone}>{st.label}</Badge>}
                      </div>
                    </td>
                    <td className="num px-3 text-right whitespace-nowrap">
                      <span>{money(r.po_total, r.currency)}</span>
                      {r.currency && r.currency !== 'CHF' && r.approval_amount_chf && <span className="block text-[11.5px] text-muted">CHF {money(r.approval_amount_chf, null, { decimals: false })}</span>}
                    </td>
                    <td className="px-3">
                      <div className="flex items-center gap-2.5">
                        <RouteMini r={r} />
                        <StatePill state={r.state} stage={r.stage} />
                      </div>
                    </td>
                    <td className="px-3 whitespace-nowrap">
                      {r.current_step ? (
                        <span>
                          <span className="num text-muted">
                            {r.current_step.position}/{r.current_step.total}
                          </span>{' '}
                          {r.current_step.approver_name}
                        </span>
                      ) : r.state === 'NEEDS_REVIEW' ? (
                        <span className="text-muted">Purchasing</span>
                      ) : r.po_number ? (
                        <span className="num text-muted">{r.po_number}</span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="px-3 pr-5">
                      <div className="flex gap-1">
                        {r.issue_counts.blocking > 0 && <Badge tone="review">{r.issue_counts.blocking} blocking</Badge>}
                        {r.issue_counts.blocking === 0 && r.issue_counts.warning > 0 && <Badge>{r.issue_counts.warning} to check</Badge>}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {data && rows.length === 0 && <Empty title={q ? 'No requisition matches that search' : 'No requisitions in this view'} />}
        </Panel>
      </Page>
    </>
  )
}
