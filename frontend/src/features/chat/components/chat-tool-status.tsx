"use client";

import type { McpToolOperation } from "@/features/chat/schemas/chat-stream";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { Check, Database, LoaderCircle, TriangleAlert } from "lucide-react";

const MCP_TOOL_LABELS: Record<McpToolOperation, string> = {
  list_products: "读取商品目录",
  search_products: "查询商品",
  search_billing_references: "查询客户、仓库或经手人",
  preview_sales_order: "校验销售单预览",
  get_sales_order: "查询销售单详情",
  list_sales_orders: "查询销售单列表",
  external_business: "查询外部业务数据",
};

const MCP_TOOL_OPERATION_SET = new Set<string>(Object.keys(MCP_TOOL_LABELS));

export function isMcpToolOperation(value: string): value is McpToolOperation {
  return MCP_TOOL_OPERATION_SET.has(value);
}

export const ChatToolStatus: ToolCallMessagePartComponent = ({ toolName, status, isError }) => {
  const operation = isMcpToolOperation(toolName) ? toolName : "external_business";
  const failed = isError === true || status?.type === "incomplete";
  const running = !failed && status?.type === "running";
  const label = MCP_TOOL_LABELS[operation];
  const message = failed ? `${label}未完成` : running ? `正在${label}` : `已完成${label}`;
  const Icon = failed ? TriangleAlert : running ? LoaderCircle : Check;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-state={failed ? "failed" : running ? "running" : "completed"}
      className="my-2 flex w-fit max-w-full items-center gap-2.5 rounded-xl border border-[#deded8] bg-[#f7f7f3] px-3 py-2 text-sm text-[#4d4d48] shadow-[0_1px_0_rgba(0,0,0,0.03)] dark:border-white/10 dark:bg-white/[0.06] dark:text-[#c9c9c3]"
    >
      <span className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-white text-[#55554f] shadow-[0_1px_3px_rgba(0,0,0,0.08)] dark:bg-white/10 dark:text-[#e4e4df]">
        <Icon
          aria-hidden="true"
          className={running ? "size-3.5 animate-spin motion-reduce:animate-none" : "size-3.5"}
        />
      </span>
      <span className="min-w-0 truncate">{message}</span>
      <span className="shrink-0 rounded-md border border-[#d8d8d1] bg-white/80 px-1.5 py-0.5 text-[10px] font-medium tracking-[0.12em] text-[#77776f] uppercase dark:border-white/10 dark:bg-white/[0.05] dark:text-[#aaa9a2]">
        MCP
      </span>
      <Database aria-hidden="true" className="size-3.5 shrink-0 opacity-45" />
    </div>
  );
};
