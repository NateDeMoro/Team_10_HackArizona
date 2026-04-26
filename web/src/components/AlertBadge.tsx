import type { AlertLevel } from "@/lib/api";
import { ALERT_BG, ALERT_COPY } from "@/lib/format";
import { cn } from "@/lib/utils";

export function AlertBadge({
  level,
  className,
}: {
  level: AlertLevel;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        ALERT_BG[level],
        className,
      )}
    >
      {ALERT_COPY[level]}
    </span>
  );
}
