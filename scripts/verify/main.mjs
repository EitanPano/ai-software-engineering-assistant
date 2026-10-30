import { realpathSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Node resolves the main module through links but leaves argv[1] as typed, so both sides are
// resolved before they are compared; a mismatch would end the script silently with exit 0.
export function isMain(moduleUrl, argv1) {
  const real = (file) => {
    try {
      return realpathSync(file)
    } catch {
      return path.resolve(file)
    }
  }
  return argv1 !== undefined && real(fileURLToPath(moduleUrl)) === real(path.resolve(argv1))
}
