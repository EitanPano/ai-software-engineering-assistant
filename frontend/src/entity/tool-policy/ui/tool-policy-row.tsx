import type { ReactNode } from 'react'

// One tool: its name above its control on a phone, beside it from `sm`. `action` is the select,
// composed by the widget.
export function ToolPolicyRow({ name, action }: { name: string; action: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground sm:flex-row sm:items-center sm:justify-between">
      <span className="min-w-0 font-medium break-all">{name}</span>
      {action}
    </div>
  )
}
