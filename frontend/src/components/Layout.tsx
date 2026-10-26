import { Command } from 'cmdk'
import { ArrowLeftRight, Boxes, FileCheck2, Home, Inbox, Search, Settings2, UserRoundCheck, Workflow } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useApprovers, useRequisitions, useStatus } from '@/api/hooks'
import { useLiveUpdates } from '@/lib/live'
import { cn, money, STATE_LABEL } from '@/lib/format'
import { Kbd } from './ui'

const NAV = [
  { to: '/', label: 'Needs attention', icon: Home, end: true },
  { to: '/requisitions', label: 'Requisitions', icon: Inbox },
  { to: '/workflow', label: 'Workflow', icon: Workflow },
  { to: '/orders', label: 'Purchase orders', icon: FileCheck2 },
  { to: '/master', label: 'Master data', icon: Boxes },
]
const NAV_2 = [
  { to: '/approver', label: 'Approver view', icon: UserRoundCheck },
  { to: '/demo', label: 'Inbox simulator', icon: Settings2 },
]

export function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const connected = useLiveUpdates()
  const status = useStatus()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[228px] shrink-0 flex-col border-r border-hairline bg-[#f0f0f3]/70 px-3 py-4 md:flex">
        <div className="mb-5 flex items-center gap-2.5 px-2">
          <Logo />
          <div className="leading-tight">
            <p className="text-[13.5px] font-semibold">Requisitions</p>
            <p className="text-[11.5px] text-muted">Purchasing desk</p>
          </div>
        </div>
        <button
          onClick={() => setPaletteOpen(true)}
          className="mb-4 flex h-8 items-center gap-2 rounded-lg bg-surface px-2.5 text-[13px] text-muted shadow-[0_0_0_0.5px_rgb(0_0_0/0.12)] hover:text-ink"
        >
          <Search size={14} />
          Search
          <span className="ml-auto flex gap-0.5">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </nav>
        <div className="my-3 h-px bg-hairline" />
        <nav className="flex flex-col gap-0.5">
          {NAV_2.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </nav>
        <div className="mt-auto space-y-1.5 px-2 text-[11.5px] text-muted">
          <StatusDot ok={connected} label={connected ? 'Live updates on' : 'Reconnecting…'} />
          <StatusDot ok={status.data?.erp === 'ok'} label={status.data?.erp === 'ok' ? 'ERP connected' : 'ERP unreachable'} />
          <StatusDot ok={!!status.data?.api_key_configured} label={status.data?.api_key_configured ? `AI: ${status.data.extraction_model}` : 'AI key missing (cache only)'} />
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
      <Palette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  )
}

function Logo() {
  // A route line with three stations: the product in one mark.
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden>
      <rect width="28" height="28" rx="8" fill="var(--color-accent)" />
      <path d="M6 14h16" stroke="white" strokeOpacity=".55" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="7.5" cy="14" r="2.4" fill="white" />
      <circle cx="14" cy="14" r="2.4" fill="white" />
      <circle cx="20.5" cy="14" r="2.4" fill="none" stroke="white" strokeWidth="1.6" />
    </svg>
  )
}

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof Home; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] transition-colors',
          isActive ? 'bg-surface font-medium text-ink shadow-[0_0_0_0.5px_rgb(0_0_0/0.08),0_1px_2px_rgb(0_0_0/0.04)]' : 'text-ink-2 hover:bg-black/[0.04]',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={15} className={isActive ? 'text-accent' : 'text-muted'} />
          {label}
        </>
      )}
    </NavLink>
  )
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <p className="flex items-center gap-2">
      <span className={cn('size-1.5 rounded-full', ok ? 'bg-good' : 'bg-review')} />
      {label}
    </p>
  )
}

/** Translucent sticky page header. */
export function PageHeader({ title, sub, actions, children }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-canvas/80 backdrop-blur-xl backdrop-saturate-150">
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5 sm:px-8">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[20px] font-semibold">{title}</h1>
          {sub && <div className="mt-0.5 text-[13px] text-muted">{sub}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  )
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto max-w-[1500px] px-4 py-6 sm:px-8', className)}>{children}</div>
}

function Palette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const navigate = useNavigate()
  const reqs = useRequisitions()
  const approvers = useApprovers()
  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }
  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Search"
      overlayClassName="fixed inset-0 z-50 bg-black/15 backdrop-blur-[2px]"
      contentClassName="fixed top-[14vh] left-1/2 z-50 w-[calc(100vw-32px)] max-w-[620px] -translate-x-1/2 overflow-hidden rounded-2xl bg-surface shadow-[var(--shadow-pop)]"
    >
      <div className="flex items-center gap-2.5 border-b border-hairline px-4">
        <Search size={16} className="text-muted" />
        <Command.Input autoFocus placeholder="Find a requisition, supplier, person or page" className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-faint" />
      </div>
      <Command.List className="max-h-[56vh] overflow-y-auto p-2 text-[13.5px] [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[12px] [&_[cmdk-group-heading]]:text-muted">
        <Command.Empty className="px-3 py-8 text-center text-muted">No match.</Command.Empty>
        <Command.Group heading="Requisitions">
          {(reqs.data ?? []).map((r) => (
            <Item key={r.id} value={`${r.public_id} ${r.title} ${r.requester_name} ${r.supplier_name ?? r.supplier_name_doc} ${r.source_name}`} onSelect={() => go(`/r/${r.id}`)}>
              <span className="num w-[72px] text-muted">{r.public_id}</span>
              <span className="flex-1 truncate">{r.title}</span>
              <span className="text-[12px] text-muted">{STATE_LABEL[r.state]}</span>
              <span className="num w-[110px] text-right text-[12px] text-muted">{money(r.po_total, r.currency)}</span>
            </Item>
          ))}
        </Command.Group>
        <Command.Group heading="Pages">
          {[...NAV, ...NAV_2].map((n) => (
            <Item key={n.to} value={`page ${n.label}`} onSelect={() => go(n.to)}>
              <n.icon size={15} className="text-muted" /> {n.label}
            </Item>
          ))}
        </Command.Group>
        <Command.Group heading="Approver views">
          {(approvers.data ?? []).map((a) => (
            <Item key={a.id} value={`approver ${a.name} ${a.role_label}`} onSelect={() => go(`/approver/${a.id}`)}>
              <ArrowLeftRight size={14} className="text-muted" />
              <span className="flex-1">{a.name}</span>
              <span className="text-[12px] text-muted">{a.role_label}</span>
              {a.pending > 0 && <span className="num text-[12px] text-accent">{a.pending} waiting</span>}
            </Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  )
}

function Item({ children, value, onSelect }: { children: ReactNode; value: string; onSelect: () => void }) {
  return (
    <Command.Item value={value} onSelect={onSelect} className="flex h-9 cursor-default items-center gap-2.5 rounded-lg px-2.5 data-[selected=true]:bg-accent-soft data-[selected=true]:text-ink">
      {children}
    </Command.Item>
  )
}
