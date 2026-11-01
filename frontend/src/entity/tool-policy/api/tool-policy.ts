import { queryOptions } from '@tanstack/react-query'

import { call } from '@/shared/api/call'
import { getApiToolPolicyByMcpServerId } from '@/shared/api/generated'
import { getApiToolPolicyByMcpServerIdQueryKey } from '@/shared/api/generated/@tanstack/react-query.gen'

export const toolPolicyKey = (mcpServerId: string) =>
  getApiToolPolicyByMcpServerIdQueryKey({ path: { mcpServerId } })

export const toolPolicyQuery = (mcpServerId: string) =>
  queryOptions({
    queryKey: toolPolicyKey(mcpServerId),
    queryFn: ({ signal }) => call(getApiToolPolicyByMcpServerId({ path: { mcpServerId }, signal })),
  })
