// A hook that throws after the payload parsed, to prove readPayload's crash handlers block.
import { allow, readPayload } from '../../lib/guardrail.mjs'

await readPayload()
null.boom
allow()
