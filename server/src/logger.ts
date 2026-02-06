type Level = "debug" | "info" | "warn" | "error";

const levels: Record<Level, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const currentLevel = (process.env.LOG_LEVEL as Level) || "info";
const currentRank = levels[currentLevel] ?? 1;

function log(level: Level, event: string, payload?: Record<string, unknown>) {
  if (levels[level] < currentRank) return;
  const line = {
    ts: new Date().toISOString(),
    level,
    event,
    ...payload,
  };
  console.log(JSON.stringify(line));
}

function summarize(value: unknown) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) {
    return { type: "array", length: value.length };
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return { type: "object", keys: keys.slice(0, 8) };
  }
  return value;
}

export const logger = {
  debug: (event: string, payload?: Record<string, unknown>) =>
    log("debug", event, payload),
  info: (event: string, payload?: Record<string, unknown>) =>
    log("info", event, payload),
  warn: (event: string, payload?: Record<string, unknown>) =>
    log("warn", event, payload),
  error: (event: string, payload?: Record<string, unknown>) =>
    log("error", event, payload),
  summarize,
};
