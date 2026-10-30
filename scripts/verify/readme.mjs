import { readFileSync } from 'node:fs'
import path from 'node:path'
import { extractConfiguration, renderConfiguration } from '../readme.mjs'

const FIX = 'run `node scripts/readme.mjs --configuration`'

// The README's Configuration block must equal what the example env files render to.
export function readmeCheck(root) {
  let text
  try {
    text = readFileSync(path.join(root, 'README.md'), 'utf8')
  } catch {
    return { name: 'readme', ok: false, detail: `README.md is missing; ${FIX} after creating it` }
  }
  let current
  try {
    current = extractConfiguration(text)
  } catch (error) {
    return { name: 'readme', ok: false, detail: `${error.message}; ${FIX}` }
  }
  let expected
  try {
    expected = renderConfiguration(root)
  } catch (error) {
    return { name: 'readme', ok: false, detail: `cannot render the table: ${error.message}` }
  }
  if (current !== expected) {
    return { name: 'readme', ok: false, detail: `the Configuration table is stale; ${FIX}` }
  }
  return { name: 'readme', ok: true, detail: '' }
}
