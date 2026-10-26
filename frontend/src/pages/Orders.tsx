import { FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMaster, usePurchaseOrders } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { Badge, Empty, Panel, Skeleton } from '@/components/ui'
import { dateTime, money } from '@/lib/format'

export function OrdersPage() {
  const { data, isPending } = usePurchaseOrders()
  const master = useMaster()
  const supplier = (id: unknown) => master.data?.suppliers.find((s) => s.id === id)?.name ?? String(id ?? '—')
  const booked = data?.filter((p) => p.po_number) ?? []
  return (
    <>
      <PageHeader title="Purchase orders" sub={data ? `${booked.length} booked in the ERP${data.length > booked.length ? `, ${data.length - booked.length} failed attempts` : ''}` : 'Loading'} />
      <Page>
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-[13px]">
            <thead className="border-b border-hairline text-[12px] text-muted">
              <tr>
                <th className="py-2.5 pl-5 font-medium">Order</th>
                <th className="px-3 font-medium">Requisition</th>
                <th className="px-3 font-medium">Supplier</th>
                <th className="px-3 text-right font-medium">Total, net</th>
                <th className="px-3 font-medium">Delivery</th>
                <th className="px-3 font-medium">ERP response</th>
                <th className="px-3 pr-5 font-medium">When</th>
              </tr>
            </thead>
            <tbody>
              {isPending && (
                <tr>
                  <td colSpan={7} className="p-5">
                    <Skeleton className="h-5" />
                  </td>
                </tr>
              )}
              {data?.map((po) => (
                <tr key={po.id} className="border-b border-hairline align-top last:border-0">
                  <td className="num py-3 pl-5 font-medium">{po.po_number ?? <span className="text-bad">not booked</span>}</td>
                  <td className="px-3 py-3">
                    <Link to={`/r/${po.requisition_id}`} className="num text-accent">
                      {po.requisition_public_id}
                    </Link>
                  </td>
                  <td className="px-3 py-3">{supplier(po.request.supplier_id)}</td>
                  <td className="num px-3 py-3 text-right">{money(po.request.total as number, po.request.currency as string)}</td>
                  <td className="px-3 py-3">{String(po.request.requested_delivery_date ?? '—')}</td>
                  <td className="max-w-[340px] px-3 py-3">
                    {po.http_status === 201 || po.http_status === 200 ? (
                      <Badge tone={po.warnings.length ? 'review' : 'good'}>{po.warnings.length ? `booked, ${po.warnings.length} warning${po.warnings.length > 1 ? 's' : ''}` : 'booked'}</Badge>
                    ) : (
                      <Badge tone="bad">{po.http_status ? `rejected, HTTP ${po.http_status}` : 'unreachable'}</Badge>
                    )}
                    {[...po.warnings, ...(((po.response as { problems?: string[] }).problems as string[]) ?? [])].map((w, i) => (
                      <p key={i} className="mt-1 text-[12px] text-muted">
                        {w}
                      </p>
                    ))}
                  </td>
                  <td className="px-3 py-3 pr-5 whitespace-nowrap text-muted">{dateTime(po.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.length === 0 && (
            <Empty icon={<FileCheck2 size={26} />} title="No orders yet">
              Fully approved requisitions with a delivery date are booked here.
            </Empty>
          )}
        </Panel>
      </Page>
    </>
  )
}
