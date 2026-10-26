import { useState, type ReactNode } from 'react'
import { useMaster } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { Badge, Panel, Skeleton } from '@/components/ui'
import { cn, money } from '@/lib/format'

const TABS = ['Suppliers', 'Cost centers', 'People', 'Approval limits', 'GL accounts', 'Exchange rates'] as const

export function MasterPage() {
  const { data } = useMaster()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Suppliers')
  return (
    <>
      <PageHeader title="Master data" sub="Read-only. Loaded into the database from master_data.json; suppliers created from an issue appear here too.">
        <div className="mx-auto flex max-w-[1500px] gap-1 overflow-x-auto px-4 pb-2.5 sm:px-8">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={cn('h-7 shrink-0 rounded-full px-3 text-[12.5px]', tab === t ? 'bg-ink text-white' : 'text-ink-2 hover:bg-black/5')}>
              {t}
            </button>
          ))}
        </div>
      </PageHeader>
      <Page>
        <Panel className="overflow-x-auto">
          {!data ? (
            <div className="p-5">
              <Skeleton className="h-40" />
            </div>
          ) : tab === 'Suppliers' ? (
            <Table head={['ID', 'Name', 'VAT / UID', 'Country', 'Currency', 'Terms', 'Status']}>
              {data.suppliers.map((s) => (
                <tr key={s.id}>
                  <Td muted>{s.id}</Td>
                  <Td>
                    {s.name} {s.preferred && <Badge tone="accent">preferred</Badge>} {s.created_by_clerk && <Badge>added by purchasing</Badge>}
                  </Td>
                  <Td muted>{s.vat_id ?? '—'}</Td>
                  <Td>{s.country}</Td>
                  <Td>{s.default_currency}</Td>
                  <Td muted>{s.payment_terms_days ? `${s.payment_terms_days} days` : '—'}</Td>
                  <Td>{s.status === 'active' ? <Badge tone="good">active</Badge> : <Badge tone="bad">{s.status}</Badge>}</Td>
                </tr>
              ))}
            </Table>
          ) : tab === 'Cost centers' ? (
            <Table head={['Code', 'Name', 'Owner', 'Department', 'Department head']}>
              {data.cost_centers.map((c) => (
                <tr key={c.code}>
                  <Td muted>{c.code}</Td>
                  <Td>{c.name}</Td>
                  <Td>{c.owner_name}</Td>
                  <Td>{c.department_name}</Td>
                  <Td>{c.head_name}</Td>
                </tr>
              ))}
            </Table>
          ) : tab === 'People' ? (
            <Table head={['ID', 'Name', 'Email', 'Role', 'Notes']}>
              {data.employees.map((e) => (
                <tr key={e.id}>
                  <Td muted>{e.id}</Td>
                  <Td>{e.name}</Td>
                  <Td muted>{e.email}</Td>
                  <Td>{e.role.replace(/_/g, ' ')}</Td>
                  <Td muted>{e.deputy_for ? `Deputy for ${e.deputy_for} (stand-ins are out of scope)` : e.default_cost_center ? `Usually books to ${e.default_cost_center}` : ''}</Td>
                </tr>
              ))}
            </Table>
          ) : tab === 'Approval limits' ? (
            <Table head={['Band', 'From CHF', 'Up to CHF (inclusive)', 'Approvers, in order']}>
              {data.approval_bands.map((b) => (
                <tr key={b.position}>
                  <Td muted>{b.position}</Td>
                  <Td num>{money(b.lower, null, { decimals: false })}</Td>
                  <Td num>{b.upper ? money(b.upper, null, { decimals: false }) : 'no limit'}</Td>
                  <Td>{b.role_labels.join(', then ')}</Td>
                </tr>
              ))}
            </Table>
          ) : tab === 'GL accounts' ? (
            <Table head={['Code', 'Name']}>
              {data.gl_accounts.map((g) => (
                <tr key={g.code}>
                  <Td muted>{g.code}</Td>
                  <Td>{g.name}</Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Table head={['Currency', 'Rate to CHF']}>
              {Object.entries(data.fx_rates).map(([c, r]) => (
                <tr key={c}>
                  <Td>{c}</Td>
                  <Td num>{Number(r).toFixed(2)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
        {tab === 'Exchange rates' && <p className="mt-3 px-1 text-[12.5px] text-muted">Fixed rates from the master data. In production these come from a daily ECB feed.</p>}
      </Page>
    </>
  )
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <table className="w-full text-left text-[13px]">
      <thead className="border-b border-hairline text-[12px] text-muted">
        <tr>
          {head.map((h) => (
            <th key={h} className="px-3 py-2.5 font-medium first:pl-5">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="[&_tr]:border-b [&_tr]:border-hairline [&_tr:last-child]:border-0">{children}</tbody>
    </table>
  )
}

function Td({ children, muted, num }: { children: ReactNode; muted?: boolean; num?: boolean }) {
  return <td className={cn('px-3 py-2.5 first:pl-5', muted && 'text-muted', num && 'num')}>{children}</td>
}
