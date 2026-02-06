import { config } from "./config.js";

export async function embedText(text: string): Promise<number[]> {
  if (!text) return [];
  const url = `${config.ollama.baseUrl.replace(/\/$/, "")}/api/embeddings`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: config.ollama.embedModel,
      prompt: text,
    }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`ollama embeddings error ${resp.status}: ${body}`);
  }
  const data = (await resp.json()) as { embedding?: number[] };
  if (!data.embedding) {
    throw new Error("ollama embeddings missing embedding field");
  }
  return data.embedding;
}
