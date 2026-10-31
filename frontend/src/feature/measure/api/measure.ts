import { useMutation, useQueryClient } from '@tanstack/react-query'

import { evalRunListKey } from '@/entity/eval-run/api/eval-run'
import { call } from '@/shared/api/call'
import { postApiEvalRun } from '@/shared/api/generated'

import { MEASURE_COPY } from '../model'

// Starts an eval run: a paid action, so it is sent by a click and nothing else.
// - `retry: false` and `networkMode: 'always'`: the query client already never retries a
//   mutation, but a mutation paused offline would resume by itself on reconnect
//   (`QueryClient.mount`). 'always' sends it at once and lets it fail, so a start made offline is
//   never replayed later.
// - No loader, query or effect sends it; `Try again`, focus and reconnect only re-read.
// On success the list is stale from now on and shows the new run, polling until it settles.
export function useStartEvalRun() {
  const queryClient = useQueryClient()
  return useMutation({
    retry: false,
    networkMode: 'always',
    mutationFn: () => call(postApiEvalRun(), MEASURE_COPY),
    // Settled, not success: a refused start (409) means another run holds the slot, and the list
    // must show it (and poll it) rather than stay as it was. The refetch is a free read.
    onSettled: () => queryClient.invalidateQueries({ queryKey: evalRunListKey() }),
  })
}
