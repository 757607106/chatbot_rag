"use client";

import { MessagePartPrimitive, type ImageMessagePartComponent } from "@assistant-ui/react";
import { ExpandIcon, ImageOffIcon, LoaderCircleIcon, XIcon } from "lucide-react";
import { useRef, useState } from "react";

import { cn } from "@/lib/utils";

export const ImageMessagePart: ImageMessagePartComponent = ({ image, filename }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const alt = filename ? `文档图片：${filename}` : "知识库文档图片";

  const openPreview = () => {
    if (loadState === "loaded") dialogRef.current?.showModal();
  };

  return (
    <figure className="group/image my-4 w-fit max-w-full overflow-hidden rounded-2xl border border-black/10 bg-[#f7f7f5] shadow-[0_12px_32px_-24px_rgba(0,0,0,0.55)] dark:border-white/15 dark:bg-[#171717]">
      <button
        type="button"
        onClick={openPreview}
        disabled={loadState !== "loaded"}
        aria-label={loadState === "loaded" ? `放大查看${alt}` : alt}
        className="relative block max-w-full overflow-hidden bg-[#ecece8] text-left outline-none focus-visible:ring-2 focus-visible:ring-[#0d0d0d] focus-visible:ring-offset-2 disabled:cursor-default dark:bg-[#242424] dark:focus-visible:ring-white dark:focus-visible:ring-offset-black"
      >
        <div
          className={cn(
            "absolute inset-0 flex min-h-48 min-w-72 items-center justify-center transition-opacity duration-300 motion-reduce:transition-none",
            loadState === "loading" ? "opacity-100" : "pointer-events-none opacity-0",
          )}
          aria-hidden="true"
        >
          <LoaderCircleIcon className="size-5 animate-spin text-[#7d7d75] motion-reduce:animate-none" />
        </div>

        {loadState !== "error" && (
          <MessagePartPrimitive.Image
            alt={alt}
            loading="lazy"
            onLoad={() => setLoadState("loaded")}
            onError={() => setLoadState("error")}
            className={cn(
              "block max-h-[68vh] min-h-48 w-auto max-w-full object-contain transition-[opacity,transform] duration-300 motion-reduce:transition-none",
              loadState === "loaded" ? "opacity-100" : "opacity-0",
              "group-hover/image:scale-[1.005] motion-reduce:group-hover/image:scale-100",
            )}
          />
        )}

        {loadState === "error" && (
          <div
            role="img"
            aria-label={`${alt}加载失败`}
            className="flex min-h-48 min-w-72 flex-col items-center justify-center gap-2 px-8 py-10 text-center"
          >
            <ImageOffIcon className="size-6 text-[#77776f]" />
            <span className="text-sm text-[#5d5d57] dark:text-[#b8b8b0]">图片暂时无法显示</span>
          </div>
        )}

        {loadState === "loaded" && (
          <span className="absolute top-3 right-3 flex size-8 items-center justify-center rounded-full bg-black/55 text-white opacity-0 shadow-sm backdrop-blur-sm transition-opacity group-hover/image:opacity-100 group-focus-visible/image:opacity-100 motion-reduce:transition-none">
            <ExpandIcon className="size-4" aria-hidden="true" />
          </span>
        )}
      </button>

      <figcaption className="flex min-h-10 items-center gap-2 border-t border-black/10 px-3.5 py-2 text-xs text-[#5d5d57] dark:border-white/10 dark:text-[#b8b8b0]">
        <span className="truncate">{filename ?? "文档图片"}</span>
      </figcaption>

      <dialog
        ref={dialogRef}
        aria-label={`${alt}预览`}
        onClick={(event) => {
          if (event.target === event.currentTarget) event.currentTarget.close();
        }}
        className="m-auto max-h-[94dvh] max-w-[96vw] overflow-visible bg-transparent p-0 backdrop:bg-black/80 backdrop:backdrop-blur-sm"
      >
        <div className="relative flex max-h-[94dvh] max-w-[96vw] items-center justify-center">
          <img
            src={image}
            alt={alt}
            className="max-h-[92dvh] max-w-[94vw] rounded-xl object-contain shadow-2xl"
          />
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label="关闭图片预览"
            className="absolute -top-3 -right-3 flex size-10 items-center justify-center rounded-full bg-white text-black shadow-xl outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black motion-reduce:transition-none dark:bg-white"
          >
            <XIcon className="size-5" />
          </button>
        </div>
      </dialog>
    </figure>
  );
};
