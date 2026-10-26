import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as PopoverPrimitive from '@radix-ui/react-popover'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { X } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn, initials, type Tone } from '@/lib/format'

// ---------------------------------------------------------------- button

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'good'
  size?: 'sm' | 'md'
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] font-medium whitespace-nowrap transition-[background,box-shadow,color,transform] duration-150 select-none active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45',
        size === 'sm' ? 'h-7 px-2.5 text-[12.5px]' : 'h-8.5 px-3.5 text-[13.5px]',
        variant === 'primary' && 'bg-accent text-white shadow-[0_1px_0_rgb(255_255_255/0.15)_inset,0_1px_2px_rgb(0_0_0/0.12)] hover:bg-accent-hover',
        variant === 'secondary' && 'bg-surface text-ink shadow-[0_0_0_0.5px_rgb(0_0_0/0.14),0_1px_2px_rgb(0_0_0/0.05)] hover:bg-sunken',
        variant === 'ghost' && 'text-ink-2 hover:bg-black/[0.045]',
        variant === 'danger' && 'bg-surface text-bad shadow-[0_0_0_0.5px_rgb(0_0_0/0.14),0_1px_2px_rgb(0_0_0/0.05)] hover:bg-bad-soft',
        variant === 'good' && 'bg-good text-white shadow-[0_1px_2px_rgb(0_0_0/0.12)] hover:brightness-95',
        className,
      )}
      {...rest}
    >
      {loading && <span className="size-3 animate-spin rounded-full border-[1.5px] border-current border-r-transparent" />}
      {children}
    </button>
  )
})

// ---------------------------------------------------------------- badge

const TONES: Record<Tone, string> = {
  neutral: 'bg-black/[0.05] text-ink-2',
  accent: 'bg-accent-soft text-accent',
  review: 'bg-review-soft text-review',
  good: 'bg-good-soft text-good',
  bad: 'bg-bad-soft text-bad',
}

export function Badge({ tone = 'neutral', children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={cn('inline-flex h-5 items-center gap-1 rounded-full px-2 text-[11.5px] font-medium whitespace-nowrap', TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

// ---------------------------------------------------------------- surfaces

export function Panel({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-[var(--radius-panel)] bg-surface shadow-[var(--shadow-panel)]', className)} {...rest}>
      {children}
    </div>
  )
}

export function SectionTitle({ children, aside, className }: { children: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-center justify-between gap-3', className)}>
      <h2 className="text-[15px] font-semibold">{children}</h2>
      {aside}
    </div>
  )
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn('inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] border border-hairline-strong bg-surface px-1 text-[10.5px] font-medium text-muted', className)}>
      {children}
    </kbd>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton h-4', className)} />
}

export function Avatar({ name, size = 24, tone = 'neutral' }: { name?: string | null; size?: number; tone?: 'neutral' | 'accent' | 'good' | 'bad' | 'muted' }) {
  return (
    <span
      title={name ?? undefined}
      style={{ width: size, height: size, fontSize: size * 0.38 }}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold tracking-tight',
        tone === 'neutral' && 'bg-[#e8e8ed] text-ink-2',
        tone === 'accent' && 'bg-accent text-white',
        tone === 'good' && 'bg-good text-white',
        tone === 'bad' && 'bg-bad text-white',
        tone === 'muted' && 'bg-[#f0f0f3] text-faint',
      )}
    >
      {initials(name)}
    </span>
  )
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-sm text-[13px] text-muted">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- form controls

const control =
  'h-8.5 w-full rounded-[var(--radius-control)] bg-surface px-2.5 text-[13.5px] shadow-[0_0_0_0.5px_rgb(0_0_0/0.16)] transition-shadow outline-none placeholder:text-faint focus:shadow-[0_0_0_1px_var(--color-accent),0_0_0_4px_var(--color-accent-soft)] disabled:bg-sunken disabled:text-muted'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(control, className)} {...rest} />
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(control, 'h-auto min-h-20 py-2 leading-snug', className)} {...rest} />
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select
      ref={ref}
      className={cn(control, 'appearance-none bg-[url("data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A//www.w3.org/2000/svg%27%20width%3D%2710%27%20height%3D%276%27%3E%3Cpath%20d%3D%27M1%201l4%204%204-4%27%20stroke%3D%27%236e6e73%27%20fill%3D%27none%27%20stroke-width%3D%271.4%27/%3E%3C/svg%3E")] bg-[position:right_10px_center] bg-no-repeat pr-7', className)}
      {...rest}
    >
      {children}
    </select>
  )
})

export function Label({ children, hint, htmlFor }: { children: ReactNode; hint?: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 flex items-baseline justify-between gap-2 text-[12.5px] font-medium text-ink-2">
      {children}
      {hint && <span className="font-normal text-muted">{hint}</span>}
    </label>
  )
}

// ---------------------------------------------------------------- overlays

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  width = 440,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  description?: ReactNode
  children: ReactNode
  width?: number
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/20 backdrop-blur-[2px] data-[state=open]:animate-[fade_150ms]" />
        <DialogPrimitive.Content
          style={{ maxWidth: width }}
          className="fixed top-[18vh] left-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 rounded-2xl bg-surface p-5 shadow-[var(--shadow-pop)] outline-none"
        >
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <DialogPrimitive.Title className="text-[16px] font-semibold">{title}</DialogPrimitive.Title>
              {description && <DialogPrimitive.Description className="mt-1 text-[13px] text-muted">{description}</DialogPrimitive.Description>}
            </div>
            <DialogPrimitive.Close className="-mt-1 -mr-1 rounded-md p-1 text-muted hover:bg-black/5" aria-label="Close">
              <X size={16} />
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export function Popover({ trigger, children, width = 320, align = 'start' }: { trigger: ReactNode; children: ReactNode; width?: number; align?: 'start' | 'center' | 'end' }) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align={align}
          sideOffset={6}
          style={{ width }}
          className="z-50 rounded-xl bg-surface p-3.5 text-[13px] shadow-[var(--shadow-pop)] outline-none"
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content sideOffset={5} className="z-50 max-w-72 rounded-lg bg-ink px-2.5 py-1.5 text-[12px] leading-snug text-white shadow-lg">
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

export const TooltipProvider = TooltipPrimitive.Provider
