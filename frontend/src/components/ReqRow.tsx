import { AlertTriangle, Link2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ReqSummary } from '@/api/client'
import { ago, cn, money } from '@/lib/format'
import { StatePill } from './domain'

/** Compact row used in the attention groups and feeds. */
export function ReqRow({ r, compact = false }: { r: ReqSummary; compact?: boolean }) {
  return (
    <Link to={`/r/${r.id}`} className="group flex items-center gap-4 px-4 py-2.5 transition-colors hover:bg-sunken">
      <span className="num w-[68px] shrink-0 text-[12.5px] whitespace-nowrap text-muted">{r.public_id}</span>
      <div className={cn("min-w-0", compact ? "flex-1" : "w-[30%] shrink-0")}>
        <p className="truncate font-medium">{r.title || r.source_name}</p>
        <p className="truncate text-[12.5px] text-muted">
          {r.requester_name ?? 'Unknown requester'}
          {(r.supplier_name || r.supplier_name_doc) && <> for {r.supplier_name ?? r.supplier_name_doc}</>}
        </p>
      </div>
      {!compact && r.top_issue && (
        <p className="hidden min-w-0 flex-1 items-start gap-1.5 text-[12.5px] leading-snug text-ink-2 md:flex">
          <AlertTriangle size={13} className={cn('mt-0.5 shrink-0', r.issue_counts.blocking ? 'text-review' : 'text-faint')} />
          <span className="line-clamp-2">{r.top_issue}</span>
        </p>
      )}
      {!compact && r.linked_to_public_id && (
        <span className="hidden items-center gap-1 text-[12px] text-muted sm:flex">
          <Link2 size={12} /> {r.linked_to_public_id}
        </span>
      )}
      {!compact && <span className="num hidden w-[112px] shrink-0 text-right text-[13px] sm:block">{money(r.po_total, r.currency)}</span>}
      <div className={cn('flex shrink-0 flex-col items-end gap-1', !compact && 'w-[132px]')}>
        <StatePill state={r.state} stage={r.stage} />
        <span className="text-[11.5px] text-faint">{ago(r.received_at)}</span>
      </div>
    </Link>
  )
}
