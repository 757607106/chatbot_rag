"use client";

import { LoaderCircleIcon, PlayIcon, SearchIcon } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { runRetrievalTest } from "@/features/knowledge/api/knowledge-api";
import type {
  KnowledgeScope,
  RetrievalCandidate,
  RetrievalTestResult,
} from "@/features/knowledge/schemas/knowledge";

export function KnowledgeRetrievalPanel({
  scope,
  onError,
}: {
  scope: KnowledgeScope;
  onError: (error: unknown) => void;
}) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [candidateTopK, setCandidateTopK] = useState(50);
  const [threshold, setThreshold] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RetrievalTestResult | null>(null);

  useEffect(() => setResult(null), [scope.knowledgeBaseId]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRunning(true);
    try {
      const parsedThreshold = threshold.trim() === "" ? null : Number(threshold);
      setResult(
        await runRetrievalTest(scope, {
          query,
          top_k: topK,
          candidate_top_k: candidateTopK,
          score_threshold: parsedThreshold,
        }),
      );
    } catch (caught) {
      onError(caught);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <form
        onSubmit={(event) => void submit(event)}
        className="h-fit rounded-xl border border-black/10 bg-[#fafafa] p-4 dark:border-white/10 dark:bg-[#151515]"
      >
        <h2 className="text-sm font-medium">直接检索</h2>
        <p className="mt-1 text-xs leading-5 text-[#777] dark:text-[#aaa]">
          仅检索当前知识库，不进入 Agent 和回答生成。
        </p>
        <label className="mt-5 block text-xs font-medium" htmlFor="retrieval-query">
          测试问题
        </label>
        <textarea
          id="retrieval-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          rows={5}
          placeholder="输入希望验证的知识库问题"
          className="mt-2 w-full resize-y rounded-lg border border-black/15 bg-white p-3 text-sm leading-6 outline-none focus:border-black/40 dark:border-white/15 dark:bg-black dark:focus:border-white/40"
          required
        />
        <div className="mt-4 grid grid-cols-2 gap-3">
          <NumberField label="最终 Top K" value={topK} min={1} max={50} onChange={setTopK} />
          <NumberField
            label="向量候选"
            value={candidateTopK}
            min={topK}
            max={500}
            onChange={setCandidateTopK}
          />
        </div>
        <label className="mt-4 block text-xs font-medium" htmlFor="score-threshold">
          向量分数阈值（可选）
        </label>
        <input
          id="score-threshold"
          type="number"
          step="any"
          value={threshold}
          onChange={(event) => setThreshold(event.target.value)}
          placeholder="不限制"
          className="mt-2 h-9 w-full rounded-lg border border-black/15 bg-white px-3 text-sm outline-none focus:border-black/40 dark:border-white/15 dark:bg-black dark:focus:border-white/40"
        />
        <button
          type="submit"
          disabled={running || query.trim().length === 0 || candidateTopK < topK}
          className="mt-5 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-[#0d0d0d] text-sm text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {running ? (
            <LoaderCircleIcon className="size-4 animate-spin" />
          ) : (
            <PlayIcon className="size-4" />
          )}
          {running ? "正在召回" : "运行召回"}
        </button>
      </form>

      <div className="min-w-0">
        {result === null ? (
          <div className="grid min-h-72 place-items-center rounded-xl border border-dashed border-black/15 px-6 text-center dark:border-white/20">
            <div>
              <SearchIcon className="mx-auto size-7 text-[#999]" />
              <p className="mt-3 text-sm font-medium">等待测试查询</p>
              <p className="mt-1 text-xs text-[#777] dark:text-[#aaa]">
                结果会展示向量排名、重排排名、分数和原始切片。
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-black/10 pb-4 text-xs dark:border-white/10">
              <span>
                <b className="font-medium">{result.final_results.length}</b> 个最终结果
              </span>
              <span>
                <b className="font-medium">{result.vector_candidates.length}</b> 个向量候选
              </span>
              <span>总耗时 {result.total_elapsed_ms.toFixed(2)} ms</span>
              <span className="text-[#777] dark:text-[#aaa]">
                重排：{rerankStatusLabel(result.rerank_status)}
              </span>
            </div>
            {result.final_results.map((candidate) => (
              <RetrievalResultCard
                key={`${candidate.document_id}:${candidate.chunk_index}`}
                candidate={candidate}
              />
            ))}
            <details className="rounded-xl border border-black/10 dark:border-white/10">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                查看全部向量候选
              </summary>
              <div className="border-t border-black/10 dark:border-white/10">
                {result.vector_candidates.map((candidate) => (
                  <div
                    key={`${candidate.document_id}:${candidate.chunk_index}`}
                    className="border-t border-black/[0.07] px-4 py-3 first:border-t-0 dark:border-white/10"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <b className="font-medium">向量 #{candidate.vector_rank}</b>
                      <span className="font-mono text-[#666] dark:text-[#aaa]">
                        {candidate.vector_score.toFixed(6)}
                      </span>
                      <span className="truncate text-[#777] dark:text-[#aaa]">
                        {candidate.source}
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-[#444] dark:text-[#ccc]">
                      {candidate.content}
                    </p>
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-xs font-medium">
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-2 h-9 w-full rounded-lg border border-black/15 bg-white px-3 text-sm outline-none focus:border-black/40 dark:border-white/15 dark:bg-black dark:focus:border-white/40"
      />
    </label>
  );
}

function RetrievalResultCard({ candidate }: { candidate: RetrievalCandidate }) {
  return (
    <article className="rounded-xl border border-black/10 p-4 dark:border-white/10">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full bg-[#0d0d0d] px-2 py-1 text-white dark:bg-white dark:text-black">
          #{candidate.final_rank}
        </span>
        <b className="font-medium">{candidate.source}</b>
        <span className="text-[#777] dark:text-[#aaa]">切片 {candidate.chunk_index + 1}</span>
        <span className="ml-auto font-mono text-[#666] dark:text-[#aaa]">
          向量 #{candidate.vector_rank} · {candidate.vector_score.toFixed(6)}
          {candidate.rerank_score === null ? "" : ` · 重排 ${candidate.rerank_score.toFixed(6)}`}
        </span>
      </div>
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6 text-[#333] dark:text-[#d4d4d4]">
        {candidate.content}
      </pre>
    </article>
  );
}

function rerankStatusLabel(status: RetrievalTestResult["rerank_status"]): string {
  if (status === "succeeded") return "成功";
  if (status === "fallback") return "失败后回退向量顺序";
  return "已跳过";
}
