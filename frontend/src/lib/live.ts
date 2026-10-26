import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

export type LiveEvent = { type: string; id?: number; state?: string; stage?: string | null; new?: boolean; running?: boolean }

/**
 * Server-sent events: refresh whatever changed, without polling.
 *
 * Only visible tabs stay connected. Each stream holds one of the browser's six HTTP/1.1
 * connections per host for good, so six open tabs would leave none for requests and the
 * app would hang. A tab coming back reconnects and refetches what it missed.
 */
export function useLiveUpdates(onEvent?: (ev: LiveEvent) => void) {
  const qc = useQueryClient()
  const cb = useRef(onEvent)
  useEffect(() => {
    cb.current = onEvent
  }, [onEvent])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let es: EventSource | null = null
    let pending: number | undefined
    const touched = new Set<number>()
    const flush = () => {
      pending = undefined
      qc.invalidateQueries({ queryKey: ['requisitions'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      qc.invalidateQueries({ queryKey: ['workflow'] })
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['approvers'] })
      qc.invalidateQueries({ queryKey: ['samples'] })
      qc.invalidateQueries({ queryKey: ['purchase-orders'] })
      touched.forEach((id) => qc.invalidateQueries({ queryKey: ['requisition', id] }))
      touched.clear()
    }
    const onMessage = (msg: MessageEvent<string>) => {
      const ev = JSON.parse(msg.data) as LiveEvent
      if (ev.id) touched.add(ev.id)
      if (ev.type === 'notification') qc.invalidateQueries({ queryKey: ['outbox'] })
      if (ev.type === 'settings') qc.invalidateQueries({ queryKey: ['settings'] })
      if (ev.type === 'reset') qc.invalidateQueries()
      cb.current?.(ev)
      // Batch bursts (a pipeline emits several stage events per email).
      if (pending === undefined) pending = window.setTimeout(flush, 150)
    }
    const connect = () => {
      if (es) return
      es = new EventSource('/api/events')
      es.onopen = () => setConnected(true)
      es.onerror = () => setConnected(false)
      es.onmessage = onMessage
    }
    const disconnect = () => {
      es?.close()
      es = null
      setConnected(false)
    }
    const onVisibility = () => {
      if (document.hidden) return disconnect()
      connect()
      qc.invalidateQueries()
    }

    if (!document.hidden) connect()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      disconnect()
      if (pending) window.clearTimeout(pending)
    }
  }, [qc])
  return connected
}
