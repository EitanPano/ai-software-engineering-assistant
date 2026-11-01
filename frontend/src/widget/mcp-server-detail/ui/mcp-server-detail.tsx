import { useSuspenseQuery } from '@tanstack/react-query'
import { ListChecksIcon, WrenchIcon } from 'lucide-react'
import { Link } from 'react-router'

import { mcpServerQuery } from '@/entity/mcp-server/api/mcp-server'
import { canReview, enabledLabel, needsReview, pinLabel, pinTone } from '@/entity/mcp-server/model'
import { toolPolicyQuery } from '@/entity/tool-policy/api/tool-policy'
import { ToolPolicyRow } from '@/entity/tool-policy/ui/tool-policy-row'
import { PolicySelect } from '@/feature/set-policy/ui/policy-select'
import { ToggleServerButton } from '@/feature/toggle-server/ui/toggle-server-button'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { EmptyState } from '@/shared/ui/pattern/empty-state'
import { Section } from '@/shared/ui/pattern/page-layout'

// One server: its status and the two things an admin does to it (review its listing, turn it off
// or on), then each tool's policy. The page reads the stored state only and calls no server.
export function McpServerDetail({ id }: { id: string }) {
  const { data: server } = useSuspenseQuery(mcpServerQuery(id))
  const { data: policy } = useSuspenseQuery(toolPolicyQuery(id))

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Section title={server.name}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={pinTone(server.pinStatus)}>{pinLabel(server.pinStatus)}</Badge>
          <Badge variant={server.enabled ? 'success' : 'muted'}>
            {enabledLabel(server.enabled)}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          A conversation started while a server is off never gets its tools, even after the server
          is back on. Turning a server off stops its tools at the next call. Accepting a listing
          enables the server. Existing conversations keep their tools and deny a changed one.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          {canReview(server) ? (
            <Button asChild variant={needsReview(server) ? 'default' : 'outline'}>
              <Link to={`/mcp-server/${id}/listing`}>
                <ListChecksIcon aria-hidden />
                Review listing
              </Link>
            </Button>
          ) : null}
          <ToggleServerButton id={id} enabled={server.enabled} />
        </div>
      </Section>
      <Section title="Tools">
        <p className="text-sm text-muted-foreground">
          A tool with no rule is denied. A policy takes effect on the next call.
        </p>
        {policy.items.length === 0 ? (
          <EmptyState
            icon={WrenchIcon}
            title="No tools yet"
            description="Tools appear here once the server has been read and its listing accepted."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {policy.items.map((item) => (
              <li key={item.toolName}>
                <ToolPolicyRow
                  name={item.toolName}
                  action={<PolicySelect mcpServerId={id} policy={item} />}
                />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}
