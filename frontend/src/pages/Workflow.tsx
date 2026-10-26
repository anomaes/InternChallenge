import { useNavigate } from 'react-router-dom'
import { useWorkflow } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { Panel } from '@/components/ui'
import { cn } from '@/lib/format'

type Node = { id: string; label: string; x: number; y: number; view?: string; tone: 'neutral' | 'review' | 'accent' | 'good' | 'bad' }

const W = 150
const H = 66
const ROW = 150
const DOWN = 340
const NODES: Node[] = [
  { id: 'INBOX', label: 'Inbox', x: 20, y: ROW, view: 'processing', tone: 'neutral' },
  { id: 'PROCESSING', label: 'Processing', x: 250, y: ROW, view: 'processing', tone: 'neutral' },
  { id: 'NEEDS_REVIEW', label: 'Needs review', x: 480, y: ROW, view: 'review', tone: 'review' },
  { id: 'PENDING_APPROVAL', label: 'Pending approval', x: 710, y: ROW, view: 'approval', tone: 'accent' },
  { id: 'APPROVED', label: 'Approved', x: 940, y: ROW, view: 'order', tone: 'good' },
  { id: 'ORDERED', label: 'Ordered', x: 1170, y: ROW, view: 'done', tone: 'good' },
  { id: 'CLOSED_DUPLICATE', label: 'Closed as duplicate', x: 480, y: DOWN, view: 'closed', tone: 'neutral' },
  { id: 'REJECTED', label: 'Rejected', x: 710, y: DOWN, view: 'closed', tone: 'bad' },
]
const at = (id: string) => NODES.find((n) => n.id === id)!
const R = (id: string) => ({ x: at(id).x + W, y: at(id).y + H / 2 })
const L = (id: string) => ({ x: at(id).x, y: at(id).y + H / 2 })
const T = (id: string, dx = 0) => ({ x: at(id).x + W / 2 + dx, y: at(id).y })
const B = (id: string, dx = 0) => ({ x: at(id).x + W / 2 + dx, y: at(id).y + H })

type Edge = { d: string; label?: string; lx?: number; ly?: number; anchor?: 'start' | 'middle' | 'end'; dashed?: boolean; strong?: boolean }
const line = (a: { x: number; y: number }, b: { x: number; y: number }) => `M${a.x},${a.y} L${b.x - 2},${b.y}`
const mid = (a: string, b: string) => (R(a).x + L(b).x) / 2

const EDGES: Edge[] = [
  { d: line(R('INBOX'), L('PROCESSING')), strong: true, label: 'email arrives', lx: mid('INBOX', 'PROCESSING'), ly: ROW + 22 },
  { d: line(R('PROCESSING'), L('NEEDS_REVIEW')), strong: true, label: 'uncertain', lx: mid('PROCESSING', 'NEEDS_REVIEW'), ly: ROW + 22 },
  { d: line(R('NEEDS_REVIEW'), L('PENDING_APPROVAL')), strong: true, label: 'resolved', lx: mid('NEEDS_REVIEW', 'PENDING_APPROVAL'), ly: ROW + 22 },
  { d: line(R('PENDING_APPROVAL'), L('APPROVED')), strong: true, label: 'all approve', lx: mid('PENDING_APPROVAL', 'APPROVED'), ly: ROW + 22 },
  { d: line(R('APPROVED'), L('ORDERED')), strong: true, label: 'ERP books', lx: mid('APPROVED', 'ORDERED'), ly: ROW + 22 },
  {
    d: `M${T('PROCESSING').x},${ROW} C${T('PROCESSING').x},60 ${T('PENDING_APPROVAL').x},60 ${T('PENDING_APPROVAL').x},${ROW - 2}`,
    label: 'clean: straight to the first approver',
    lx: (T('PROCESSING').x + T('PENDING_APPROVAL').x) / 2,
    ly: 72,
  },
  { d: `M${B('NEEDS_REVIEW').x},${B('NEEDS_REVIEW').y} L${T('CLOSED_DUPLICATE').x},${DOWN - 2}`, label: 'duplicate', lx: B('NEEDS_REVIEW').x - 8, ly: 285, anchor: 'end' },
  { d: `M${B('PENDING_APPROVAL', 40).x},${B('PENDING_APPROVAL').y} L${T('REJECTED', 40).x},${DOWN - 2}`, label: 'any step rejects', lx: B('PENDING_APPROVAL', 40).x + 8, ly: 285, anchor: 'start' },
  { d: `M${R('NEEDS_REVIEW').x - 30},${B('NEEDS_REVIEW').y} L${T('REJECTED', -40).x},${DOWN - 2}`, label: 'clerk rejects', lx: 655, ly: 262, anchor: 'start' },
  {
    d: `M${B('REJECTED').x},${DOWN + H} C${B('REJECTED').x},${DOWN + 130} ${L('NEEDS_REVIEW').x - 120},${DOWN + 130} ${L('NEEDS_REVIEW').x - 60},${ROW + H} L${L('NEEDS_REVIEW').x - 4},${ROW + H - 6}`,
    label: 'corrected and resubmitted: the chain starts again from step 1',
    lx: 560,
    ly: DOWN + 118,
    dashed: true,
  },
]

const TONE: Record<Node['tone'], { fill: string; stroke: string; text: string }> = {
  neutral: { fill: '#ffffff', stroke: '#d2d2d7', text: '#1d1d1f' },
  review: { fill: '#fff5e6', stroke: '#f6d9a8', text: '#a35a00' },
  accent: { fill: '#eef1fc', stroke: '#c9d3f5', text: '#2b4bcf' },
  good: { fill: '#eaf6ef', stroke: '#bfe3cd', text: '#1e7a4c' },
  bad: { fill: '#fdeeec', stroke: '#f4c6c1', text: '#c0352b' },
}

export function WorkflowPage() {
  const { data } = useWorkflow()
  const navigate = useNavigate()
  const count = (id: string) => {
    const c = Object.fromEntries((data?.states ?? []).map((s) => [s.state, s.count]))
    return id === 'PROCESSING' ? (c.PROCESSING ?? 0) + (c.EXTRACTED ?? 0) : (c[id] ?? 0)
  }

  return (
    <>
      <PageHeader title="Workflow" sub="Every requisition moves through these states. Counts are live; click a state to see its requisitions." />
      <Page className="space-y-6">
        <Panel className="overflow-x-auto p-4 sm:p-6">
          <svg viewBox="0 45 1340 445" className="min-w-[960px]" role="img" aria-label="Requisition workflow">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#a1a1a6" />
              </marker>
              <marker id="arrow-strong" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#424245" />
              </marker>
            </defs>
            {EDGES.map((e, i) => (
              <g key={i}>
                <path d={e.d} fill="none" stroke={e.strong ? '#424245' : '#a1a1a6'} strokeWidth={e.strong ? 1.4 : 1.2} strokeDasharray={e.dashed ? '4 4' : undefined} markerEnd={`url(#${e.strong ? 'arrow-strong' : 'arrow'})`} />
                {e.label && (
                  <text x={e.lx} y={e.ly} textAnchor={e.anchor ?? 'middle'} className="fill-[#6e6e73] text-[13px]">
                    {e.label}
                  </text>
                )}
              </g>
            ))}
            {NODES.map((n) => {
              const t = TONE[n.tone]
              const c = count(n.id)
              return (
                <g
                  key={n.id}
                  role="link"
                  tabIndex={0}
                  className="cursor-pointer outline-none [&:focus-visible_rect]:stroke-[#2b4bcf] [&:hover_rect]:stroke-[#a1a1a6]"
                  onClick={() => navigate(`/requisitions?view=${n.view}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/requisitions?view=${n.view}`)}
                >
                  <rect x={n.x} y={n.y} width={W} height={H} rx={14} fill={t.fill} stroke={t.stroke} strokeWidth={1.2} />
                  <text x={n.x + 16} y={n.y + 26} className="text-[15px] font-medium" fill="#1d1d1f">
                    {n.label}
                  </text>
                  <text x={n.x + 16} y={n.y + 50} className={cn('num text-[20px] font-semibold')} fill={c ? t.text : '#a1a1a6'}>
                    {c}
                  </text>
                </g>
              )
            })}
          </svg>
        </Panel>
        <div className="grid gap-4 text-[13px] text-ink-2 md:grid-cols-3">
          <Panel className="p-5">
            <h2 className="mb-1.5 text-[14px] font-semibold text-ink">Needs review</h2>
            <p>Anything the system can't establish waits for purchasing: an unknown or blocked supplier, a missing cost center, a document that contradicts itself, a suspected duplicate, or a step nobody may approve. A clean requisition skips it.</p>
          </Panel>
          <Panel className="p-5">
            <h2 className="mb-1.5 text-[14px] font-semibold text-ink">Pending approval</h2>
            <p>One approver at a time, in band order: cost center owner, department head, finance, CFO, CEO. Nobody approves their own request, and nothing is approved automatically. Changing the amount, supplier, cost center or requester restarts the chain.</p>
          </Panel>
          <Panel className="p-5">
            <h2 className="mb-1.5 text-[14px] font-semibold text-ink">Approved to ordered</h2>
            <p>The ERP needs a delivery date; most emails don't give one, so purchasing confirms it. The order is then booked once, with an idempotency key. If the ERP rejects it or is down, the requisition stays approved and shows why.</p>
          </Panel>
        </div>
      </Page>
    </>
  )
}
