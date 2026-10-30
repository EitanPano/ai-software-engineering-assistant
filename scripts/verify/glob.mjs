// `**/` is any number of directories (or none), a trailing `/**` everything below, `*` one
// path segment's characters.
export function toRegExp(glob) {
  let source = ''
  for (let i = 0; i < glob.length; i++) {
    if (glob.startsWith('**/', i)) (source += '(?:.*/)?'), (i += 2)
    else if (glob.startsWith('/**', i) && i + 3 === glob.length) (source += '/.*'), (i += 2)
    else if (glob[i] === '*') source += '[^/]*'
    else source += glob[i].replace(/[.+?^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${source}$`)
}

// The files, with backslashes read as slashes, that any glob matches.
export function matching(files, globs) {
  const patterns = globs.map(toRegExp)
  return files.filter((file) => {
    const normal = file.replaceAll('\\', '/')
    return patterns.some((pattern) => pattern.test(normal))
  })
}
