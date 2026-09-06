import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

const components = {
  h1: (props: React.ComponentPropsWithoutRef<"h1">) => (
    <h1 className="font-display mb-3 mt-5 text-[1.7rem] font-medium tracking-tight text-foreground first:mt-0" {...props} />
  ),
  h2: (props: React.ComponentPropsWithoutRef<"h2">) => (
    <h2 className="font-display mb-2.5 mt-6 text-[1.35rem] font-medium tracking-tight text-foreground" {...props} />
  ),
  h3: (props: React.ComponentPropsWithoutRef<"h3">) => (
    <h3 className="font-display mb-2 mt-5 text-[1.12rem] font-medium text-foreground" {...props} />
  ),
  h4: (props: React.ComponentPropsWithoutRef<"h4">) => (
    <h4 className="mb-2 mt-4 text-base font-medium text-foreground" {...props} />
  ),
  p: (props: React.ComponentPropsWithoutRef<"p">) => (
    <p className="my-3 break-words text-[15px] leading-relaxed text-muted-foreground" {...props} />
  ),
  ul: (props: React.ComponentPropsWithoutRef<"ul">) => (
    <ul className="my-3 list-disc space-y-1.5 pl-5 text-muted-foreground" {...props} />
  ),
  ol: (props: React.ComponentPropsWithoutRef<"ol">) => (
    <ol className="my-3 list-decimal space-y-1.5 pl-5 text-muted-foreground" {...props} />
  ),
  li: (props: React.ComponentPropsWithoutRef<"li">) => (
    <li className="break-words leading-relaxed marker:text-primary" {...props} />
  ),
  blockquote: (props: React.ComponentPropsWithoutRef<"blockquote">) => (
    <blockquote
      className="my-4 border-l-2 border-primary/40 pl-4 font-display text-lg italic text-foreground/80"
      {...props}
    />
  ),
  a: (props: React.ComponentPropsWithoutRef<"a">) => (
    <a
      className="break-all text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  strong: (props: React.ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-semibold text-foreground" {...props} />
  ),
  em: (props: React.ComponentPropsWithoutRef<"em">) => (
    <em className="font-display italic text-foreground/90" {...props} />
  ),
  hr: (props: React.ComponentPropsWithoutRef<"hr">) => (
    <hr className="my-5 border-border/70" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<"code">) => (
    <code
      className="break-all rounded-sm border border-border/60 bg-muted px-1.5 py-0.5 font-mono text-[0.83em] text-foreground"
      {...props}
    />
  ),
  pre: (props: React.ComponentPropsWithoutRef<"pre">) => (
    <pre className="my-4 overflow-x-auto border border-border/70 bg-card p-3 font-mono text-[13px]" {...props} />
  ),
  table: (props: React.ComponentPropsWithoutRef<"table">) => (
    <div className="my-4 overflow-x-auto border border-border/70">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  thead: (props: React.ComponentPropsWithoutRef<"thead">) => (
    <thead className="bg-muted/60 text-left" {...props} />
  ),
  th: (props: React.ComponentPropsWithoutRef<"th">) => (
    <th className="border-b border-border px-2 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-foreground sm:px-3" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<"td">) => (
    <td className="border-b border-border/50 px-2 py-2 align-top text-muted-foreground last:border-0 sm:px-3" {...props} />
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
