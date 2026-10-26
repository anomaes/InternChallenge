import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  api,
  type Approver,
  type Dashboard,
  type Master,
  type Notification,
  type PurchaseOrder,
  type Queue,
  type ReqDetail,
  type ReqSummary,
  type Sample,
  type Settings,
  type Status,
  type Workflow,
} from './client'

export const keys = {
  list: ['requisitions'] as const,
  detail: (id: number) => ['requisition', id] as const,
}

export const useRequisitions = () => useQuery({ queryKey: keys.list, queryFn: () => api.get<ReqSummary[]>('/requisitions') })
export const useRequisition = (id: number) =>
  useQuery({ queryKey: keys.detail(id), queryFn: () => api.get<ReqDetail>(`/requisitions/${id}`) })
export const useDashboard = () => useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<Dashboard>('/dashboard') })
export const useWorkflow = () => useQuery({ queryKey: ['workflow'], queryFn: () => api.get<Workflow>('/workflow') })
export const useMaster = () =>
  useQuery({ queryKey: ['master'], queryFn: () => api.get<Master>('/master'), staleTime: 60_000 })
export const usePurchaseOrders = () =>
  useQuery({ queryKey: ['purchase-orders'], queryFn: () => api.get<PurchaseOrder[]>('/purchase-orders') })
export const useSettings = () => useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
export const useStatus = () =>
  useQuery({ queryKey: ['status'], queryFn: () => api.get<Status>('/status'), refetchInterval: 10_000 })
export const useOutbox = () => useQuery({ queryKey: ['outbox'], queryFn: () => api.get<Notification[]>('/outbox') })
export const useSamples = () => useQuery({ queryKey: ['samples'], queryFn: () => api.get<Sample[]>('/demo/samples') })
export const useApprovers = () => useQuery({ queryKey: ['approvers'], queryFn: () => api.get<Approver[]>('/approvers') })
export const useQueue = (emp: string) =>
  useQuery({ queryKey: ['queue', emp], queryFn: () => api.get<Queue>(`/approvers/${emp}/queue`) })

/** A mutation on one requisition: the server returns the fresh detail, which replaces the cache. */
export function useReqAction<V>(id: number, run: (vars: V) => Promise<ReqDetail>, success?: string | ((d: ReqDetail) => string)) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: (data) => {
      qc.setQueryData(keys.detail(id), data)
      qc.invalidateQueries({ queryKey: keys.list })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      if (success) toast.success(typeof success === 'function' ? success(data) : success)
    },
    onError: (err: Error) => toast.error(err.message),
  })
}
