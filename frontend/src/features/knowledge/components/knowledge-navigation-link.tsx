import { DatabaseIcon } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

export function KnowledgeNavigationLink({
  compact = false,
  active = false,
}: {
  compact?: boolean;
  active?: boolean;
}) {
  return (
    <Link
      href="/knowledge"
      aria-current={active ? "page" : undefined}
      title={compact ? "知识库" : undefined}
      className={cn(
        "flex h-9 items-center rounded-lg text-sm transition-colors",
        compact ? "justify-center px-0" : "gap-2 px-2.5",
        active
          ? "bg-black/[0.08] text-[#0d0d0d] dark:bg-white/15 dark:text-[#ececec]"
          : "text-[#5d5d5d] hover:bg-black/[0.06] hover:text-[#0d0d0d] dark:text-[#b4b4b4] dark:hover:bg-white/10 dark:hover:text-[#ececec]",
      )}
    >
      <DatabaseIcon className="size-4 shrink-0" />
      {!compact && <span>知识库</span>}
    </Link>
  );
}
