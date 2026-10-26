import { CheckCircle2, Inbox, Mail } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Link } from 'react-router-dom'
import { useDashboard } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { ReqRow } from '@/components/ReqRow'
import { Button, Empty, Panel, Skeleton } from '@/components/ui'
import { cn } from '@/lib/format'

const STRIP = [
  { key: 'needs_review', label: 'Needs review', to: '/requisitions?view=review', tone: 'text-review' },
  { key: 'pending_approval', label: 'Waiting for approvers', to: '/requisitions?view=approval', tone: 'text-accent' },
  { key: 'ready_to_order', label: 'Approved, to order', to: '/requisitions?view=order', tone: 'text-good' },
  { key: 'order_failed', label: 'Order failed', to: '/requisitions?view=order', tone: 'text-bad' },
  { key: 'ordered', label: 'Ordered', to: '/orders', tone: 'text-ink' },
]

export function HomePage() {
  const { data, isPending } = useDashboard()
  const counts = data?.counts ?? {}
  const processing = counts.processing ?? 0

  return (
    <>
      <PageHeader
        title="Needs attention"
        sub={
          data
            ? counts.total === 0
              ? 'No requisitions yet.'
              : `${counts.needs_review ?? 0} waiting for you${processing ? `, ${processing} being processed` : ''}`
            : 'Loading'
        }
        actions={
          <Link to="/demo">
            <Button>
              <Mail size={14} /> Deliver emails
            </Button>
          </Link>
        }
      />
      <Page className="space-y-6">
        <Panel className="grid grid-cols-2 divide-hairline sm:grid-cols-5 sm:divide-x">
          {STRIP.map((s) => (
            <Link key={s.key} to={s.to} className="group px-5 py-4 transition-colors first:rounded-l-[var(--radius-panel)] last:rounded-r-[var(--radius-panel)] hover:bg-sunken">
              {isPending ? (
                <Skeleton className="h-7 w-10" />
              ) : (
                <p className={cn('num text-[26px] leading-none font-semibold tracking-tight', (counts[s.key] ?? 0) === 0 ? 'text-faint' : s.tone)}>{counts[s.key] ?? 0}</p>
              )}
              <p className="mt-1.5 text-[12.5px] text-muted group-hover:text-ink-2">{s.label}</p>
            </Link>
          ))}
        </Panel>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-5">
            {isPending &&
              [0, 1].map((i) => (
                <Panel key={i} className="space-y-3 p-5">
                  <Skeleton className="w-48" />
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </Panel>
              ))}
            {data && data.groups.length === 0 && (
              <Panel>
                <Empty icon={<CheckCircle2 size={28} />} title={counts.total ? 'Nothing needs you right now' : 'The inbox is empty'}>
                  {counts.total ? (
                    'Clean requisitions went straight to their approvers. Anything uncertain will show up here.'
                  ) : (
                    <>
                      Deliver the sample emails from the <Link to="/demo" className="text-accent">inbox simulator</Link> to see them flow through.
                    </>
                  )}
                </Empty>
              </Panel>
            )}
            <AnimatePresence initial={false}>
              {data?.groups.map((g) => (
                <motion.section key={g.key} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <div className="mb-2 flex items-baseline justify-between px-1">
                    <h2 className="text-[15px] font-semibold">
                      {g.title} <span className="num ml-1 font-normal text-muted">{g.items.length}</span>
                    </h2>
                    <p className="hidden text-[12.5px] text-muted sm:block">{g.hint}</p>
                  </div>
                  <Panel className="divide-y divide-hairline overflow-hidden">
                    {g.items.map((r) => (
                      <ReqRow key={r.id} r={r} />
                    ))}
                  </Panel>
                </motion.section>
              ))}
            </AnimatePresence>
          </div>

          <aside>
            <div className="mb-2 flex items-baseline justify-between px-1">
              <h2 className="text-[15px] font-semibold">Just arrived</h2>
              <Link to="/requisitions" className="text-[12.5px] text-accent">
                All requisitions
              </Link>
            </div>
            <Panel className="overflow-hidden">
              {data && data.recent.length === 0 && <Empty icon={<Inbox size={24} />} title="Nothing yet" />}
              <ul className="divide-y divide-hairline">
                <AnimatePresence initial={false}>
                  {data?.recent.map((r) => (
                    <motion.li key={r.id} layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                      <ReqRow r={r} compact />
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            </Panel>
          </aside>
        </div>
      </Page>
    </>
  )
}
