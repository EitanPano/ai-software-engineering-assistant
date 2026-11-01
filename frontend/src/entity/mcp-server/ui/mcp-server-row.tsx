import { Link } from 'react-router'

import { Badge } from '@/shared/ui/badge'

import { enabledLabel, pinLabel, pinTone, type McpServer } from '../model'

// One server: its name as the link to its page, the pin status and whether it is on, in words.
export function McpServerRow({ server }: { server: McpServer }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3 text-card-foreground">
      <Link
        to={`/mcp-server/${server.id}`}
        className="min-w-0 font-medium break-all underline-offset-4 hover:underline"
      >
        {server.name}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={pinTone(server.pinStatus)}>{pinLabel(server.pinStatus)}</Badge>
        <Badge variant={server.enabled ? 'success' : 'muted'}>{enabledLabel(server.enabled)}</Badge>
      </div>
    </div>
  )
}
