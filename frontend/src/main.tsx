import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Layout } from './components/Layout'
import { TooltipProvider } from './components/ui'
import './index.css'
import { ApproverDecision, ApproverIndex, ApproverQueue } from './pages/Approver'
import { DemoPage } from './pages/Demo'
import { HomePage } from './pages/Home'
import { MasterPage } from './pages/Master'
import { OrdersPage } from './pages/Orders'
import { RequisitionPage } from './pages/Requisition'
import { RequisitionsPage } from './pages/Requisitions'
import { WorkflowPage } from './pages/Workflow'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: true, retry: 1 } },
})

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/requisitions', element: <RequisitionsPage /> },
      { path: '/r/:id', element: <RequisitionPage /> },
      { path: '/workflow', element: <WorkflowPage /> },
      { path: '/orders', element: <OrdersPage /> },
      { path: '/master', element: <MasterPage /> },
      { path: '/demo', element: <DemoPage /> },
      { path: '/approver', element: <ApproverIndex /> },
    ],
  },
  // The approver view stands alone: it is what an approver opens from the notification link.
  { path: '/approver/:emp', element: <ApproverQueue /> },
  { path: '/approver/:emp/r/:id', element: <ApproverDecision /> },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" toastOptions={{ className: '!rounded-xl !text-[13px] !shadow-[var(--shadow-pop)]' }} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
