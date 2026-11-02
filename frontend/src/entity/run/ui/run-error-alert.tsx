import { ErrorState } from '@/shared/ui/pattern/error-state'

import { runErrorCopy, type RunErrorCode } from '../model'

// A run that ended in failure, in our words for its `errorCode`. The send form stays enabled
// beside it: sending again is the recovery.
export function RunErrorAlert({ errorCode }: { errorCode: RunErrorCode | null }) {
  return <ErrorState title="The answer didn't finish" description={runErrorCopy(errorCode)} />
}
