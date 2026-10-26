import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Paperclip, Play, Square, Upload } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { api, type Settings } from '@/api/client'
import { useApprovers, useOutbox, useSamples, useSettings, useStatus } from '@/api/hooks'
import { Page, PageHeader } from '@/components/Layout'
import { Badge, Button, Dialog, Input, Panel, Select } from '@/components/ui'
import { cn, dateTime } from '@/lib/format'

type OkOut = { ok: boolean; message?: string | null }
type Delivered = { requisition_id: number; public_id: string } | null

export function DemoPage() {
  const qc = useQueryClient()
  const samples = useSamples()
  const settings = useSettings()
  const status = useStatus()
  const outbox = useOutbox()
  const approvers = useApprovers()
  const feeder = useQuery({ queryKey: ['feeder'], queryFn: () => api.get<OkOut>('/demo/feeder'), refetchInterval: 1500 })
  const [interval, setIntervalS] = useState('3')
  const [confirmReset, setConfirmReset] = useState(false)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['samples'] })
    qc.invalidateQueries({ queryKey: ['feeder'] })
  }
  const deliver = useMutation({
    mutationFn: (name: string) => api.post<Delivered>('/demo/deliver', { name }),
    onSuccess: (d) => (refresh(), d && toast.success(`${d.public_id} delivered`)),
    onError: (e: Error) => toast.error(e.message),
  })
  const next = useMutation({
    mutationFn: () => api.post<Delivered>('/demo/deliver-next'),
    onSuccess: (d) => (refresh(), toast(d ? `${d.public_id} delivered` : 'Every sample has been delivered')),
  })
  const all = useMutation({
    mutationFn: () => api.post<OkOut>('/demo/deliver-all', { interval_s: Number(interval) || 3 }),
    onSuccess: (d) => (refresh(), toast.success(d.message ?? 'Delivering')),
    onError: (e: Error) => toast.error(e.message),
  })
  const stop = useMutation({ mutationFn: () => api.post<OkOut>('/demo/stop'), onSuccess: refresh })
  const reset = useMutation({
    mutationFn: () => api.post<OkOut>('/demo/reset'),
    onSuccess: () => (qc.invalidateQueries(), setConfirmReset(false), toast.success('Reset: no requisitions, master data reseeded')),
  })
  const put = useMutation({
    mutationFn: (body: Partial<Settings>) => api.put<Settings>('/settings', body),
    onSuccess: (d) => qc.setQueryData(['settings'], d),
    onError: (e: Error) => toast.error(e.message),
  })
  const upload = useMutation({
    mutationFn: async (file: File) => api.post<Delivered>('/demo/upload', await file.arrayBuffer(), { 'X-Filename': file.name, 'Content-Type': 'message/rfc822' }),
    onSuccess: (d) => d && toast.success(`${d.public_id} received`, { action: { label: 'Open', onClick: () => (window.location.href = `/r/${d.requisition_id}`) } }),
    onError: (e: Error) => toast.error(e.message),
  })

  const onFiles = (files: FileList | null) => {
    Array.from(files ?? [])
      .filter((f) => f.name.toLowerCase().endsWith('.eml'))
      .forEach((f) => upload.mutate(f))
  }

  const delivered = samples.data?.filter((s) => s.requisition_id).length ?? 0
  const running = !!feeder.data?.ok
  const s = settings.data

  return (
    <>
      <PageHeader title="Inbox simulator" sub="Deliver the sample emails as if they arrived in the purchasing mailbox, drop in an unseen one, and flip the system's switches." />
      <Page className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-6">
          <div
            onDragOver={(e) => (e.preventDefault(), setDrag(true))}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => (e.preventDefault(), setDrag(false), onFiles(e.dataTransfer.files))}
            onClick={() => fileRef.current?.click()}
            className={cn(
              'flex cursor-pointer flex-col items-center rounded-[var(--radius-panel)] border-[1.5px] border-dashed px-6 py-8 text-center transition-colors',
              drag ? 'border-accent bg-accent-soft' : 'border-hairline-strong bg-surface/60 hover:border-faint',
            )}
          >
            <Upload size={22} className={drag ? 'text-accent' : 'text-faint'} />
            <p className="mt-2 font-medium">Drop an .eml file here, or click to choose one</p>
            <p className="mt-0.5 text-[13px] text-muted">It goes through the same pipeline as any email that arrives. Unseen emails are always extracted live.</p>
            <input ref={fileRef} type="file" accept=".eml,message/rfc822" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          </div>

          <Panel>
            <div className="flex flex-wrap items-center gap-2 px-5 pt-4 pb-3">
              <h2 className="mr-auto text-[15px] font-semibold">
                Sample emails <span className="num ml-1 font-normal text-muted">{delivered} of {samples.data?.length ?? 0} delivered</span>
              </h2>
              <Button size="sm" onClick={() => next.mutate()} loading={next.isPending}>
                Deliver next
              </Button>
              {running ? (
                <Button size="sm" variant="danger" onClick={() => stop.mutate()}>
                  <Square size={11} /> Stop
                </Button>
              ) : (
                <span className="flex items-center gap-1.5">
                  <Button size="sm" variant="primary" onClick={() => all.mutate()} loading={all.isPending}>
                    <Play size={11} /> Deliver all
                  </Button>
                  <span className="text-[12.5px] text-muted">every</span>
                  <Input value={interval} onChange={(e) => setIntervalS(e.target.value)} className="num h-7 w-12 text-center text-[12.5px]" aria-label="Seconds between emails" />
                  <span className="text-[12.5px] text-muted">s</span>
                </span>
              )}
            </div>
            <ul className="max-h-[560px] divide-y divide-hairline overflow-y-auto border-t border-hairline">
              {samples.data?.map((m) => (
                <li key={m.name} className="flex items-center gap-3 px-5 py-2 text-[13px]">
                  <span className="num w-[110px] shrink-0 text-[12px] text-muted">{dateTime(m.sent_at)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate">
                      {m.subject}
                      {m.has_attachment && <Paperclip size={12} className="ml-1 inline text-muted" />}
                    </p>
                    <p className="truncate text-[12px] text-muted">
                      {m.sender?.replace(/<.*>/, '').trim()}, {m.name}
                    </p>
                  </div>
                  {m.requisition_id ? (
                    <Link to={`/r/${m.requisition_id}`} className="text-[12.5px] text-accent">
                      Open
                    </Link>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => deliver.mutate(m.name)}>
                      Deliver
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel>
            <div className="px-5 pt-4 pb-3">
              <h2 className="text-[15px] font-semibold">Outbox</h2>
              <p className="text-[12.5px] text-muted">Notifications the system would send. Delivery by email is future work; the links open the approver view.</p>
            </div>
            <ul className="max-h-[420px] divide-y divide-hairline overflow-y-auto border-t border-hairline">
              {outbox.data?.length === 0 && <li className="px-5 py-6 text-center text-[13px] text-muted">Nothing sent yet.</li>}
              {outbox.data?.map((n) => (
                <li key={n.id} className="px-5 py-2.5 text-[13px]">
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium">To {n.recipient_label}</span>
                    <span className="truncate text-ink-2">{n.subject}</span>
                    <span className="ml-auto shrink-0 text-[12px] text-muted">{dateTime(n.created_at)}</span>
                  </div>
                  <p className="text-[12.5px] text-muted">{n.body}</p>
                  {n.link && (
                    <a href={n.link.replace(/^https?:\/\/[^/]+/, '')} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-[12.5px] text-accent">
                      Open the approver view <ExternalLink size={11} />
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel className="divide-y divide-hairline">
            <h2 className="px-5 pt-4 pb-3 text-[15px] font-semibold">Switches</h2>
            <Setting
              title="Decision checks"
              text="After extraction, an independent model (OpenAI Decisions API) rates how likely each routing value matches the document. Off by default; the system is correct without it."
            >
              <Toggle on={!!s?.decision_checks_enabled} onChange={(v) => put.mutate({ decision_checks_enabled: v })} label="Decision checks" />
            </Setting>
            {s?.decision_checks_enabled && (
              <div className="grid grid-cols-2 gap-3 px-5 py-3 text-[12.5px]">
                <label>
                  <span className="text-muted">Verified at or above</span>
                  <Input type="number" step="0.05" min="0" max="1" defaultValue={s.check_high} onBlur={(e) => put.mutate({ check_high: Number(e.target.value) })} className="num mt-1 h-7" />
                </label>
                <label>
                  <span className="text-muted">Blocks routing below</span>
                  <Input type="number" step="0.05" min="0" max="1" defaultValue={s.check_low} onBlur={(e) => put.mutate({ check_low: Number(e.target.value) })} className="num mt-1 h-7" />
                </label>
              </div>
            )}
            <Setting title="AI responses" text="Cached replays a stored answer for an identical (redacted) email, so the samples cost nothing to rerun. Unseen emails always go to the model.">
              <Select value={s?.llm_cache_mode ?? 'cached'} onChange={(e) => put.mutate({ llm_cache_mode: e.target.value })} className="h-7 w-[110px] text-[12.5px]">
                <option value="cached">Cached</option>
                <option value="live">Always live</option>
              </Select>
            </Setting>
          </Panel>

          <Panel className="px-5 py-4">
            <h2 className="mb-2.5 text-[15px] font-semibold">System</h2>
            <dl className="space-y-1.5 text-[13px]">
              <StatusRow label="ERP (mock_po_api.py)" value={status.data?.erp === 'ok' ? <Badge tone="good">reachable</Badge> : <Badge tone="bad">{status.data?.erp ?? '…'}</Badge>} />
              <StatusRow label="OpenAI key" value={status.data?.api_key_configured ? <Badge tone="good">configured</Badge> : <Badge tone="review">missing: cache only</Badge>} />
              <StatusRow label="Extraction model" value={status.data?.extraction_model} />
              <StatusRow label="Check model" value={status.data?.decisions_model} />
              <StatusRow label="Cached AI responses" value={status.data?.cached_responses} />
              {status.data &&
                Object.entries(status.data.counts).map(([k, v]) => <StatusRow key={k} label={k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())} value={v} />)}
            </dl>
          </Panel>

          <Panel className="px-5 py-4">
            <h2 className="mb-2 text-[15px] font-semibold">Approver views</h2>
            <p className="mb-2.5 text-[12.5px] text-muted">Keep one open in another tab to approve while you work as the clerk.</p>
            <ul className="space-y-1 text-[13px]">
              {approvers.data?.map((a) => (
                <li key={a.id} className="flex items-center gap-2">
                  <a href={`/approver/${a.id}`} target="_blank" rel="noreferrer" className="text-accent">
                    {a.name}
                  </a>
                  <span className="text-muted">{a.role_label}</span>
                  {a.pending > 0 && <Badge tone="accent">{a.pending}</Badge>}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel className="px-5 py-4">
            <h2 className="mb-1 text-[15px] font-semibold">Start over</h2>
            <p className="mb-3 text-[12.5px] text-muted">Removes every requisition, email and order record here, and reloads the master data. The ERP keeps its own orders.</p>
            <Button variant="danger" onClick={() => setConfirmReset(true)}>
              Reset all data
            </Button>
          </Panel>
        </div>
      </Page>
      <Dialog open={confirmReset} onOpenChange={setConfirmReset} title="Reset all data?" description="Every requisition, email, issue and notification is deleted. This can't be undone.">
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmReset(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => reset.mutate()} loading={reset.isPending}>
            Reset all data
          </Button>
        </div>
      </Dialog>
    </>
  )
}

function Setting({ title, text, children }: { title: string; text: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-4 px-5 py-3.5">
      <div className="flex-1">
        <p className="text-[13.5px] font-medium">{title}</p>
        <p className="mt-0.5 text-[12.5px] text-muted">{text}</p>
      </div>
      {children}
    </div>
  )
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} className={cn('relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors', on ? 'bg-good' : 'bg-[#d9d9de]')}>
      <span className={cn('absolute top-[2px] size-[18px] rounded-full bg-white shadow transition-[left] duration-200', on ? 'left-[18px]' : 'left-[2px]')} />
    </button>
  )
}

function StatusRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="num">{value ?? '—'}</dd>
    </div>
  )
}
