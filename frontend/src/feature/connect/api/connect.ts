import { useMutation, useQueryClient } from '@tanstack/react-query'

import { sourceListKey } from '@/entity/source/api/source'
import { call } from '@/shared/api/call'
import { postApiSource, postApiSourceByIdIndexing } from '@/shared/api/generated'

import { CONNECT_COPY, RETRY_COPY, toConnectBody, type ConnectInput } from '../model'

// Connects a repository; the list it joins is stale from now on. A missing repository and a
// duplicate belong to the url field.
export function useConnectSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: ConnectInput) =>
      call(postApiSource({ body: toConnectBody(values) }), CONNECT_COPY, {
        fields: { not_found: 'url', conflict: 'url' },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourceListKey() }),
  })
}

// Queues a failed source again; the list then shows it `Queued` and polls until it settles.
export function useRetryIndexing() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => call(postApiSourceByIdIndexing({ path: { id } }), RETRY_COPY),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sourceListKey() }),
  })
}
