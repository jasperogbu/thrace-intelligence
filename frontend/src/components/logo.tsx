import { cn } from "@/lib/utils"

export function Logo({
  className,
  textOnly = false,
}: {
  className?: string
  textOnly?: boolean
}) {
  if (textOnly) {
    return (
      <span
        className={cn(
          "font-display text-lg font-medium tracking-tight text-foreground",
          className,
        )}
      >
        Thrace
      </span>
    )
  }
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <img
        src="/thrace.png"
        alt="Thrace"
        className="size-6 shrink-0 rounded-sm object-cover brightness-[0.65]"
        draggable={false}
      />
      <span className="font-display text-lg font-medium tracking-tight text-foreground">
        Thrace
      </span>
    </span>
  )
}
