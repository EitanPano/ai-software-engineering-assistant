import { useQuery, useSuspenseQuery } from '@tanstack/react-query'

import { listingQuery } from '@/entity/mcp-server/api/mcp-server'
import { matchesPin } from '@/entity/mcp-server/model'
import { ListingTool } from '@/entity/mcp-server/ui/listing-tool'
import { toolPolicyQuery } from '@/entity/tool-policy/api/tool-policy'
import { effectNote } from '@/entity/tool-policy/model'
import { AcceptButton } from '@/feature/accept/ui/accept-button'
import { Section } from '@/shared/ui/pattern/page-layout'

// The live listing, read whole when the page opens. The tools come first and the accept comes
// after all of them, so the action is never above text the admin has not read. The accept sends
// the digest of this listing; a listing that changed meanwhile is a 409 and the page reloads.
export function ListingReview({ id }: { id: string }) {
  const { data: listing } = useSuspenseQuery(listingQuery(id))
  const nothingToAccept = matchesPin(listing)
  // The stored effects, read beside the listing. The listing is the decision, so a failed or slow
  // policy read shows no note and never blocks or fails the review (no suspense, no throw).
  const { data: policy } = useQuery({ ...toolPolicyQuery(id), throwOnError: false })
  // A removed tool leaves the pin on accept, so its stored effect no longer applies: no note.
  const noteOf = (name: string, change: string): string | null =>
    policy === undefined || change === 'removed'
      ? null
      : `Stored policy: ${effectNote(policy.items.find((item) => item.toolName === name)?.effect)}`

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Section title="Tools">
        <ul className="flex flex-col gap-3">
          {listing.items.map((tool) => (
            <li key={tool.name}>
              <ListingTool tool={tool} policyNote={noteOf(tool.name, tool.change)} />
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Accept">
        {nothingToAccept ? (
          <p className="text-sm text-muted-foreground">
            The live listing matches the accepted listing. There is nothing to accept.
          </p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Accepting enables the server and pins exactly what is shown above: the model reads
              these definitions. Existing conversations keep their tools and deny a changed one.
            </p>
            <div>
              <AcceptButton serverId={id} listingDigest={listing.listingDigest} />
            </div>
          </>
        )}
      </Section>
    </div>
  )
}
