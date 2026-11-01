import { TriangleAlertIcon } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert'

// A tool server that could not be reached for this run, in our words. The run goes on without
// its tools, so this is a notice in place in the log, not a failure.
export function McpServerNotice({ name }: { name: string }) {
  return (
    <Alert className="max-w-[90%]">
      <TriangleAlertIcon aria-hidden />
      <AlertTitle>
        The <span className="font-mono">{name}</span> tools are unavailable
      </AlertTitle>
      <AlertDescription>
        The agent will continue without them, so this answer may miss what they would have found.
      </AlertDescription>
    </Alert>
  )
}
