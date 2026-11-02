import type { ReactNode } from 'react'
import ReactMarkdown, { type Components, defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/shared/lib/cn'

// The one Markdown renderer. Assistant text and repository content are attacker-controlled
// (.doc/conventions.md › Agent security): react-markdown renders no raw HTML (there is no rehype-raw
// here), and `webUrl` keeps web links alone. Headings render as bold paragraphs so a message never
// adds an `h1` or `h2` to the page.
const heading = ({ children }: { children?: ReactNode }) => (
  <p className="font-semibold">{children}</p>
)

// `mailto:`, `irc:` and `xmpp:` pass react-markdown's own transform and hand a message the model
// wrote to another app, so only http, https and relative URLs stay.
function webUrl(url: string) {
  const kept = defaultUrlTransform(url)
  const scheme = /^[a-z][a-z0-9+.-]*(?=:)/i.exec(kept)?.[0].toLowerCase()
  return scheme === undefined || scheme === 'http' || scheme === 'https' ? kept : ''
}

// `URL` drops a login part and spells a lookalike domain in punycode, so its host is the real one.
function urlOf(href: string) {
  try {
    return new URL(href, window.location.origin)
  } catch {
    return null
  }
}

// A link is the one way out of a run that no approval sees: a steered model can put what it read
// in the URL and choose the words on top, and a phone has no hover to read the target. So every
// link that leaves this site shows its real host, with no exception for one that seems to show its
// own URL: each such exception was a way to lie, through a login part, an encoded host, an image's
// alt text or reversed text. The host comes first, where no label can push it off the screen, and
// shares one `bdi` with its link, so nothing in the words or around them can reorder the two. A
// destination that is not kept leaves only the words.
function ModelLink({ href, children }: { href: string | undefined; children: ReactNode }) {
  const url = href ? urlOf(href) : null
  if (url === null) return <span>{children}</span>
  const link = (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-4"
    >
      {children}
    </a>
  )
  if (url.origin === window.location.origin) return link
  return (
    <bdi dir="ltr">
      <span className="text-muted-foreground">{`(${url.host})`}</span> {link}
    </bdi>
  )
}

const components: Components = {
  h1: heading,
  h2: heading,
  h3: heading,
  h4: heading,
  h5: heading,
  h6: heading,
  p: ({ children }) => <p className="leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5">{children}</ol>,
  a: ({ children, href }) => <ModelLink href={href}>{children}</ModelLink>,
  // An image would load its URL the moment the answer renders, and the URL can carry whatever the
  // model was steered to put in it. It becomes a link showing the alt text, so nothing loads
  // without a click.
  img: ({ src, alt }) => (
    <ModelLink href={typeof src === 'string' ? src : undefined}>
      {alt?.trim() ? alt : 'Image'}
    </ModelLink>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border pl-3 text-muted-foreground">
      {children}
    </blockquote>
  ),
  pre: ({ children }) => (
    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-sm">{children}</pre>
  ),
  code: ({ children, className }) => (
    <code className={cn('rounded bg-muted px-1 font-mono text-[0.9em]', className)}>
      {children}
    </code>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-2 break-words', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={webUrl}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
