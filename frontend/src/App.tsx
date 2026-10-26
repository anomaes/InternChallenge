import { useQuery } from '@tanstack/react-query'

type Health = { status: string; erp: string }

// Placeholder until the design system lands (phase 5a): proves the
// frontend -> backend -> mock ERP wiring works.
export default function App() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async (): Promise<Health> => {
      const res = await fetch('/api/health')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    },
    refetchInterval: 5000,
  })

  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 text-neutral-900">
      <div className="rounded-2xl border border-neutral-200 bg-white px-8 py-6 shadow-sm">
        <h1 className="text-lg font-semibold tracking-tight">Purchase Requisitions</h1>
        <p className="mt-1 text-sm text-neutral-500">
          {health.isPending && 'Connecting…'}
          {health.isError && 'Backend unreachable'}
          {health.data && `API ${health.data.status} · ERP ${health.data.erp}`}
        </p>
      </div>
    </main>
  )
}
