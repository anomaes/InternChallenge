import { FileText, GitMerge, Mail, ShieldOff, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ReqDetail } from '@/api/client'
import { cn, dateTime } from '@/lib/format'
import { Badge } from './ui'

const NONE: Redacted[] = []
const NO_EVIDENCE: string[] = []

export type SourceTab = 'email' | `pdf-${number}` | 'ai'

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

type Range = { start: number; end: number; needle: string }

const byWords = (n: string) => n.split(/\s+/).map(escapeRe).join('\\s+')
// Redacted originals are stored without whitespace, so allow it anywhere ("CH9300..." matches "CH93 00...").
const byChars = (n: string) => [...n].map(escapeRe).join('\\s*')

/** Find every evidence string in the text, tolerant to whitespace differences. */
function ranges(text: string, needles: string[], pattern = byWords): Range[] {
  const out: Range[] = []
  for (const n of needles) {
    const trimmed = n.trim()
    if (trimmed.length < 3) continue
    const re = new RegExp(pattern(trimmed), 'gi')
    let m: RegExpExecArray | null
    while ((m = re.exec(text))) {
      out.push({ start: m.index, end: m.index + m[0].length, needle: n })
      if (m[0].length === 0) break
    }
  }
  out.sort((a, b) => a.start - b.start || b.end - a.end)
  const merged: typeof out = []
  for (const r of out) {
    const last = merged[merged.length - 1]
    if (last && r.start < last.end) continue
    merged.push(r)
  }
  return merged
}

type Redacted = { kind: string; placeholder: string; original: string }

const KIND_LABEL: Record<string, string> = { IBAN: 'IBAN', CARD: 'card number', AHV: 'AHV number', SECRET: 'secret' }

/** `mask` replaces redacted values with a label (for readers who shouldn't see them); otherwise they are marked. */
function Highlighted({ text, evidence, active, redacted, mask }: { text: string; evidence: string[]; active: string | null; redacted: Redacted[]; mask?: boolean }) {
  const parts = useMemo(() => {
    const hidden = ranges(text, redacted.map((x) => x.original), byChars).map((r) => ({ ...r, redacted: true }))
    const shown = ranges(text, evidence).filter((e) => !hidden.some((h) => e.start < h.end && h.start < e.end))
    const rs = [...hidden, ...shown].sort((a, b) => a.start - b.start)
    const nodes: ReactNode[] = []
    let pos = 0
    rs.forEach((r, i) => {
      if (r.start > pos) nodes.push(text.slice(pos, r.start))
      const red = 'redacted' in r ? redacted.find((x) => x.original === r.needle) : undefined
      nodes.push(
        'redacted' in r ? (
          mask ? (
            <mark key={i} className="masked">
              {KIND_LABEL[red?.kind ?? ''] ?? 'value'} hidden
            </mark>
          ) : (
            <mark key={i} className="redacted" data-placeholder={red?.placeholder}>
              {text.slice(r.start, r.end)}
            </mark>
          )
        ) : (
          <mark key={i} data-evidence={r.needle} className={cn('evidence', active && r.needle === active && 'active')}>
            {text.slice(r.start, r.end)}
          </mark>
        ),
      )
      pos = r.end
    })
    nodes.push(text.slice(pos))
    return nodes
  }, [text, evidence, active, redacted, mask])
  return <>{parts}</>
}

/** The source text split into its labelled sections (headers, body, one per attachment). */
export function sourceSections(text: string): { title: string; body: string }[] {
  const out: { title: string; body: string }[] = []
  for (const chunk of text.split(/^### /m)) {
    if (!chunk.trim()) continue
    const nl = chunk.indexOf('\n')
    out.push({ title: chunk.slice(0, nl).trim(), body: chunk.slice(nl + 1).replace(/\n+$/, '') })
  }
  return out
}

export function SourceSections({
  sections,
  evidence = NO_EVIDENCE,
  active = null,
  redacted,
  mask,
}: {
  sections: { title: string; body: string }[]
  evidence?: string[]
  active?: string | null
  redacted: Redacted[]
  mask?: boolean
}) {
  return sections.map((s) => (
    <section key={s.title} className="mb-5">
      <h3 className="mb-1.5 text-[12px] font-medium text-muted">{s.title.replace('EMAIL BODY', 'Email').replace(/^ATTACHMENT \d+: /, 'Attachment: ')}</h3>
      <pre
        className={cn(
          'font-sans text-[13px] leading-relaxed break-words whitespace-pre-wrap text-ink-2',
          s.title.startsWith('ATTACHMENT') && 'overflow-x-auto rounded-lg bg-sunken p-3 text-[12px] leading-snug break-normal whitespace-pre shadow-[0_0_0_0.5px_var(--color-hairline)]',
        )}
      >
        <Highlighted text={s.body} evidence={evidence} active={active} redacted={redacted} mask={mask} />
      </pre>
    </section>
  ))
}

/** Attachments of the requisition's own email and of the emails merged into it. */
export const allAttachments = (r: ReqDetail) => [r.email, ...r.merged_emails.map((m) => m.email)].flatMap((e) => e.attachments)

const bodySections = (sourceText: string) => sourceSections(sourceText).filter((s) => !s.title.startsWith('EMAIL HEADERS'))

/** The labelled source the model saw, split into its sections, with evidence highlighted. */
export function SourcePanel({
  r,
  tab,
  setTab,
  evidence,
  active,
}: {
  r: ReqDetail
  tab: SourceTab
  setTab: (t: SourceTab) => void
  evidence: string[]
  active: string | null
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [showRedacted, setShowRedacted] = useState(false)
  const sections = useMemo(() => bodySections(r.email.source_text), [r.email.source_text])
  const merged = useMemo(() => r.merged_emails.map((m) => ({ ...m, sections: bodySections(m.email.source_text) })), [r.merged_emails])

  useEffect(() => {
    if (!active || tab !== 'email') return
    const el = scroller.current?.querySelector(`mark[data-evidence="${CSS.escape(active)}"]`)
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [active, tab])

  useEffect(() => {
    if (showRedacted) scroller.current?.querySelector('mark.redacted')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [showRedacted])

  const pdfs = allAttachments(r).filter((a) => a.content_type === 'application/pdf')
  const lastRun = [...r.llm_runs].reverse().find((x) => x.kind === 'extract' && x.raw_output)
  const pdfIndex = tab.startsWith('pdf-') ? Number(tab.slice(4)) : -1

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-hairline px-3 py-2">
        <TabButton active={tab === 'email'} onClick={() => setTab('email')} icon={<Mail size={13} />}>
          Source
        </TabButton>
        {pdfs.map((a, i) => (
          <TabButton key={a.id} active={pdfIndex === i} onClick={() => setTab(`pdf-${i}`)} icon={<FileText size={13} />}>
            <span className="max-w-[160px] truncate">{a.filename}</span>
          </TabButton>
        ))}
        {lastRun && (
          <TabButton active={tab === 'ai'} onClick={() => setTab('ai')} icon={<Sparkles size={13} />}>
            AI output
          </TabButton>
        )}
      </div>

      {tab === 'email' && (
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 space-y-0.5 text-[12.5px]">
            <EmailMeta email={r.email} />
            {r.redaction_count > 0 && (
              <p className="pt-1.5">
                <button onClick={() => setShowRedacted((v) => !v)} aria-pressed={showRedacted} className="rounded-full transition-opacity hover:opacity-80">
                  <Badge tone="accent">
                    <ShieldOff size={11} /> {r.redaction_count} value{r.redaction_count > 1 ? 's' : ''} redacted before AI processing
                    <span className="font-normal opacity-70">, {showRedacted ? 'hide' : 'show'}</span>
                  </Badge>
                </button>
              </p>
            )}
            {r.email.thread.length > 1 && (
              <div className="pt-2">
                <p className="mb-1 text-muted">Thread, oldest first</p>
                <ol className="flex flex-wrap items-center gap-1">
                  {r.email.thread.map((m, i) => (
                    <li key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-faint">/</span>}
                      <span className={cn('rounded-full px-2 py-0.5 text-[11.5px]', m.employee_id === r.requester_id ? 'bg-accent-soft text-accent' : m.is_internal ? 'bg-black/5' : 'bg-review-soft text-review')}>
                        {m.author_name ?? m.author_email}
                        {!m.is_internal && ' (external)'}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
          <SourceSections sections={sections} evidence={evidence} active={active} redacted={showRedacted ? r.redactions : NONE} />
          {merged.map((m) => (
            <div key={m.requisition_id} className="mt-6 border-t border-hairline pt-4">
              <div className="mb-4 space-y-0.5 text-[12.5px]">
                <p className="mb-1.5 flex items-center gap-1.5 font-medium text-accent">
                  <GitMerge size={13} />
                  {m.link_type === 'correction' ? 'Applied as a correction from ' : 'Merged in from '}
                  <Link to={`/r/${m.requisition_id}`} className="num hover:underline">
                    {m.public_id}
                  </Link>
                </p>
                <EmailMeta email={m.email} />
              </div>
              <SourceSections sections={m.sections} evidence={evidence} active={active} redacted={showRedacted ? r.redactions : NONE} />
            </div>
          ))}
        </div>
      )}

      {pdfIndex >= 0 && pdfs[pdfIndex] && (
        <iframe key={pdfs[pdfIndex].id} title={pdfs[pdfIndex].filename} src={`/api/attachments/${pdfs[pdfIndex].id}#view=FitH`} className="min-h-0 w-full flex-1 bg-[#e9e9ec]" />
      )}

      {tab === 'ai' && lastRun && (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <p className="mb-2 text-[12.5px] text-muted">
            Structured output from {lastRun.model}, prompt {lastRun.prompt_version}
            {lastRun.cached ? ', replayed from cache' : ''}. The system validates and grounds every value before using it.
          </p>
          <pre className="overflow-x-auto rounded-lg bg-sunken p-3 text-[11.5px] leading-snug text-ink-2 shadow-[0_0_0_0.5px_var(--color-hairline)]">
            {JSON.stringify(JSON.parse(lastRun.raw_output!), null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function EmailMeta({ email }: { email: ReqDetail['email'] }) {
  return (
    <>
      <p>
        <span className="text-muted">From </span>
        {email.from_name} <span className="text-muted">&lt;{email.from_email}&gt;</span>
      </p>
      <p>
        <span className="text-muted">Sent </span>
        {dateTime(email.sent_at)}
        <span className="text-muted"> as </span>
        {email.source_name}
      </p>
    </>
  )
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn('flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] transition-colors', active ? 'bg-black/[0.06] font-medium text-ink' : 'text-muted hover:text-ink')}
    >
      {icon}
      {children}
    </button>
  )
}
