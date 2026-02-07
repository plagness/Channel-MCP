import { config } from "./config.js";
import { logger } from "./logger.js";
import { embedText as ollamaEmbedText } from "./ollama.js";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function extractEmbedding(result: unknown): number[] {
  if (!result || typeof result !== "object") return [];
  const data = (result as { data?: unknown }).data;
  if (!data || typeof data !== "object") return [];
  const raw = (data as { embedding?: unknown }).embedding;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item));
}

async function requestLlmMcpEmbedding(query: string): Promise<number[]> {
  const providerRaw = (config.llm.mcpProvider || "auto").toLowerCase();
  const provider = providerRaw === "ollama" || providerRaw === "auto" ? providerRaw : "auto";
  const payload: Record<string, unknown> = {
    task: "embed",
    provider,
    prompt: query,
    priority: 2,
    source: "channel-mcp",
    max_attempts: 2,
  };
  if (config.ollama.embedModel) {
    payload.model = config.ollama.embedModel;
  }

  const reqResp = await fetch(`${config.llm.mcpBaseUrl.replace(/\/$/, "")}/v1/llm/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!reqResp.ok) {
    const body = await reqResp.text();
    throw new Error(`llm_mcp enqueue failed ${reqResp.status}: ${body}`);
  }

  const reqData = (await reqResp.json()) as { job_id?: string };
  const jobId = reqData.job_id;
  if (!jobId) {
    throw new Error("llm_mcp enqueue missing job_id");
  }

  const timeoutSec = Math.max(3, config.llm.timeoutSec || 30);
  const started = Date.now();

  while ((Date.now() - started) / 1000 < timeoutSec) {
    const jobResp = await fetch(
      `${config.llm.mcpBaseUrl.replace(/\/$/, "")}/v1/jobs/${encodeURIComponent(jobId)}`,
      { method: "GET" }
    );
    if (!jobResp.ok) {
      const body = await jobResp.text();
      throw new Error(`llm_mcp job read failed ${jobResp.status}: ${body}`);
    }

    const job = (await jobResp.json()) as {
      status?: string;
      error?: string;
      result?: unknown;
    };
    const status = (job.status || "").toLowerCase();

    if (status === "done") {
      const embedding = extractEmbedding(job.result);
      if (embedding.length) {
        return embedding;
      }
      throw new Error("llm_mcp job completed with empty embedding");
    }

    if (status === "failed" || status === "error" || status === "cancelled" || status === "canceled") {
      throw new Error(`llm_mcp job ${status}: ${job.error || "unknown"}`);
    }

    await sleep(500);
  }

  throw new Error(`llm_mcp job timeout after ${timeoutSec}s`);
}

export async function embedText(query: string): Promise<number[]> {
  if ((config.llm.backend || "llm_mcp").toLowerCase() === "llm_mcp") {
    try {
      return await requestLlmMcpEmbedding(query);
    } catch (error) {
      logger.warn("llm.embed.llm_mcp_failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      if (!config.llm.fallbackOllama) {
        throw error;
      }
    }
  }

  return ollamaEmbedText(query);
}
