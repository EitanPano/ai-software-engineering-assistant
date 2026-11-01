import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/shared/lib/cn'

// The one Markdown renderer. Assistant text and repository content are attacker-controlled
// (.doc/conventions.md › Agent security): react-markdown renders no raw HTML (there is no rehype-raw
// here) and its default URL transform drops `javascript:` and other unsafe protocols. Headings
// render as bold paragraphs so a message never adds an `h1` or `h2` to the page.
const heading = ({ children }: { children?: React.ReactNode }) => (
  <p className="font-semibold">{children}</p>
)

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
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-4"
    >
      {children}
    </a>
  ),
  // An image would load its URL the moment the answer renders, and the URL can carry whatever the
  // model was steered to put in it. It becomes a link showing the alt text, so nothing loads
  // without a click.
  img: ({ src, alt }) => {
    const label = alt?.trim() ? alt : 'Image'
    return typeof src === 'string' && src !== '' ? (
      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline underline-offset-4"
      >
        {label}
      </a>
    ) : (
      <span>{label}</span>
    )
  },
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
      <table className="w-full border-collapse text-sm">{children}</table>
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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
