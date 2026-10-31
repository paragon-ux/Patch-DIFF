#!/usr/bin/env node
/** Compatibility one-shot CLI over the shared fresh evaluator. */
import { evaluateDiscovery, WAYMARK_ENGINE_VERSION, recordTiming } from "./discovery_core.mjs";
async function readInputPayload() {
  const args = process.argv.slice(2);
  const flagIdx = args.indexOf("--input-json");
  if (flagIdx !== -1 && flagIdx + 1 < args.length) {
    try {
      return JSON.parse(args[flagIdx + 1]);
    } catch (err) {
      throw Object.assign(new Error(`Invalid JSON input payload: ${err.message}`), {
        code: "INVALID_INPUT",
      });
    }
  }
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw.trim()) {
    throw Object.assign(new Error("Missing JSON input payload on stdin."), {
      code: "INVALID_INPUT",
    });
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw Object.assign(new Error(`Invalid JSON input payload: ${err.message}`), {
      code: "INVALID_INPUT",
    });
  }
}

try {
  const response = await evaluateDiscovery(await readInputPayload());
  const encodeStart = process.hrtime.bigint();
  const encoded = JSON.stringify(response) + "\n";
  recordTiming("bridge_result_encode", encodeStart);
  process.stdout.write(encoded);
} catch (error) {
  process.stdout.write(JSON.stringify({ok: false, waymark_engine_version: WAYMARK_ENGINE_VERSION,
    language: null, symbols: [], error: {code: error.code || "WAYMARK_DISCOVERY_ERROR", message: error.message}}) + "\n");
}
