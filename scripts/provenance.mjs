import { readFileSync } from 'node:fs'

// The generator writes the provenance file in a fixed shape, so a line scan for the facts needed
// (deploy, and per package its template, http.port and commands) replaces a YAML dependency.
export function readProvenance(file) {
  const result = { deploy: undefined, packages: [] }
  let text = ''
  try {
    text = readFileSync(file, 'utf8')
  } catch {
    return result
  }
  const unquote = (value) => value.replace(/\s+#.*$/, '').replace(/^['"]|['"]$/g, '')
  let section = ''
  let pkg
  let inHttp = false
  let inCommands = false
  // The command whose block is being read, so its continuation lines join onto it: a folded
  // block (`>`) joins with spaces, a literal one (`|`) with newlines.
  let folded
  let joiner = ' '
  for (const line of text.replace(/^﻿/, '').split(/\r?\n/)) {
    const top = /^([A-Za-z]\w*):\s*(.*?)\s*$/.exec(line)
    if (top !== null) {
      section = top[1]
      if (section === 'deploy') result.deploy = unquote(top[2])
      continue
    }
    if (section !== 'packages') continue
    const name = /^ {2}(['"]?)([\w.-]+)\1:\s*$/.exec(line)
    if (name !== null) {
      pkg = { name: name[2], dir: name[2], template: '', port: undefined, commands: {} }
      result.packages.push(pkg)
      inHttp = false
      inCommands = false
      folded = undefined
      continue
    }
    // Any other package-level key must not leave its facts to the previous package.
    if (/^ {2}\S/.test(line)) {
      pkg = undefined
      inHttp = false
      inCommands = false
      folded = undefined
      continue
    }
    const key = /^ {4}(\w+):\s*(.*?)\s*$/.exec(line)
    if (key !== null && pkg !== undefined) {
      inHttp = key[1] === 'http'
      inCommands = key[1] === 'commands'
      folded = undefined
      if (key[1] === 'template') pkg.template = unquote(key[2])
      continue
    }
    if (inCommands && pkg !== undefined) {
      const entry = /^ {6}(\w+):\s*(.*?)\s*$/.exec(line)
      if (entry !== null) {
        const block = /^[>|][+-]?$/.test(entry[2])
        pkg.commands[entry[1]] = block ? '' : unquote(entry[2])
        folded = block ? entry[1] : undefined
        joiner = entry[2].startsWith('|') ? '\n' : ' '
        continue
      }
      const more = /^ {8,}(\S.*?)\s*$/.exec(line)
      if (more !== null && folded !== undefined) {
        pkg.commands[folded] = `${pkg.commands[folded]}${joiner}${more[1]}`.trim()
        continue
      }
    }
    const port = /^ {6}port:\s*(\d+)\s*$/.exec(line)
    if (port !== null && inHttp && pkg !== undefined) pkg.port = Number(port[1])
  }
  return result
}
