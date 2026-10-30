import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import { applyRunEvent, initialRunView, type RunView } from '../model'

import { streamRun } from './run'

export type RunStreamState = 'streaming' | 'lost' | 'done'

// Follows one run from the start of its events (a reload replays them) and folds them into a view.
// The state belongs to the run: render it under `key={runId}` so another run starts clean.
// `onFinished` fires once, after `run_finished` has been applied. `retry` reopens a stream that
// was given up as lost; events already seen are ignored.
export function useRunStream(
  runId: string,
  onFinished?: (view: RunView) => void,
): { view: RunView; state: RunStreamState; retry: () => void } {
  const [view, apply] = useReducer(applyRunEvent, initialRunView)
  const [lost, setLost] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const onFinishedRef = useRef(onFinished)

  useEffect(() => {
    onFinishedRef.current = onFinished
  })

  useEffect(() => {
    const controller = new AbortController()
    void streamRun(runId, { signal: controller.signal, onEvent: apply }).then((outcome) => {
      if (outcome === 'lost') setLost(true)
    })
    return () => {
      controller.abort()
    }
  }, [runId, attempt])

  useEffect(() => {
    if (view.finished !== null) onFinishedRef.current?.(view)
  }, [view])

  const retry = useCallback(() => {
    setLost(false)
    setAttempt((count) => count + 1)
  }, [])

  const state: RunStreamState = view.finished !== null ? 'done' : lost ? 'lost' : 'streaming'
  return { view, state, retry }
}
