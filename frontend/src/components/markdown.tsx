import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

const components = {
  h1: (props: React.ComponentPropsWithoutRef<"h1">) => (
    <h1 className="mb-3 mt-5 text-2xl font-semibold tracking-tight text-foreground first:mt-0" {...props} />
  ),
  h2: (props: React.ComponentPropsWithoutRef<"h2">) => (
    <h2 className="mb-2.5 mt-6 text-xl font-semibold tracking-tight text-foreground" {...props} />
  ),
  h3: (props: React.ComponentPropsWithoutRef<"h3">) => (
    <h3 className="mb-2 mt-5 text-lg font-medium tracking-tight text-foreground" {...props} />
  ),
  h4: (props: React.ComponentPropsWithoutRef<"h4">) => (
    <h4 className="mb-2 mt-4 text-base font-medium text-foreground" {...props} />
  ),
  p: (props: React.ComponentPropsWithoutRef<"p">) => (
    <p className="my-3 leading-relaxed text-muted-foreground" {...props} />
  ),
  ul: (props: React.ComponentPropsWithoutRef<"ul">) => (
    <ul className="my-3 list-disc space-y-1.5 pl-6 text-muted-foreground" {...props} />
  ),
  ol: (props: React.ComponentPropsWithoutRef<"ol">) => (
    <ol className="my-3 list-decimal space-y-1.5 pl-6 text-muted-foreground" {...props} />
  ),
  li: (props: React.ComponentPropsWithoutRef<"li">) => <li className="leading-relaxed" {...props} />,
  blockquote: (props: React.ComponentPropsWithoutRef<"blockquote">) => (
    <blockquote
      className="my-4 border-l-2 border-violet-500/50 pl-4 italic text-muted-foreground"
      {...props}
    />
  ),
  a: (props: React.ComponentPropsWithoutRef<"a">) => (
    <a
      className="text-violet-500 underline decoration-violet-500/40 underline-offset-2 hover:decoration-violet-500"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  strong: (props: React.ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-semibold text-foreground" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<"code">) => (
    <code
      className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground"
      {...props}
    />
  ),
  table: (props: React.ComponentPropsWithoutRef<"table">) => (
    <div className="my-4 overflow-x-auto rounded-xl border border-border">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  thead: (props: React.ComponentPropsWithoutRef<"thead">) => (
    <thead className="bg-muted/60 text-left" {...props} />
  ),
  th: (props: React.ComponentPropsWithoutRef<"th">) => (
    <th className="border-b border-border px-3 py-2 font-medium text-foreground" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<"td">) => (
    <td className="border-b border-border/70 px-3 py-2 align-top text-muted-foreground last:border-0" {...props} />
  ),
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("text-[15px]", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
