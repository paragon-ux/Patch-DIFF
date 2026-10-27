#!/usr/bin/env node
/**
 * Read-only Waymark Engine structural discovery bridge for Patch-DIFF.
 *
 * Accepts a JSON payload on stdin (or via `--input-json <json>`):
 *   {
 *     "filename": "service.py",
 *     "content": "...",
 *     "query": optional string,
 *     "kind": optional string,
 *     "symbol_name": optional string
 *   }
 *
 * Writes `content` to an isolated temporary directory created exclusively for
 * this invocation, calls `discoverSymbolsInFile` from `waymark-engine`, deletes
 * the temporary directory in `finally`, and emits a single JSON object on stdout.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { discoverSymbolsInFile } from "waymark-engine";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const waymarkPkgPath = path.join(__dirname, "node_modules", "waymark-engine", "package.json");
const waymarkPkg = JSON.parse(fs.readFileSync(waymarkPkgPath, "utf8"));
const WAYMARK_ENGINE_VERSION = String(waymarkPkg.version || "4.1.0");

function sanitizeTempFilename(rawFilename) {
  const raw = typeof rawFilename === "string" ? rawFilename.trim() : "";
  const base = path.posix.basename(raw.replace(/\\/g, "/")).replace(/[\x00-\x1f]/g, "");
  if (!base || base === "." || base === ".." || base.startsWith(".")) {
    const ext = path.posix.extname(base);
    return ext ? `target${ext}` : "target.txt";
  }
  return base;
}

function matchesFilter(symbol, { query, kind, symbol_name: symbolName }) {
  if (typeof kind === "string" && kind.length > 0) {
    const isObjectAlias =
      kind === "object" &&
      (symbol.kind === "config_item" || symbol.kind === "config_block" || symbol.kind === "property");
    if (symbol.kind !== kind && !isObjectAlias) {
      return false;
    }
  }
  if (typeof symbolName === "string" && symbolName.length > 0) {
    const qualified = symbol.parent ? `${symbol.parent}.${symbol.name}` : null;
    if (symbol.name !== symbolName && qualified !== symbolName) {
      return false;
    }
  }
  if (typeof query === "string" && query.length > 0) {
    const q = query.toLowerCase();
    const nameMatch = String(symbol.name || "").toLowerCase().includes(q);
    const parentMatch = symbol.parent ? String(symbol.parent).toLowerCase().includes(q) : false;
    const qualifiedMatch = symbol.parent
      ? `${symbol.parent}.${symbol.name}`.toLowerCase().includes(q)
      : false;
    const sigMatch = symbol.signature ? String(symbol.signature).toLowerCase().includes(q) : false;
    if (!nameMatch && !parentMatch && !qualifiedMatch && !sigMatch) {
      return false;
    }
  }
  return true;
}

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

async function main() {
  let tmpDir = null;
  try {
    const payload = await readInputPayload();
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw Object.assign(new Error("Input payload must be a JSON object."), {
        code: "INVALID_INPUT",
      });
    }
    const { filename, content, query = null, kind = null, symbol_name = null } = payload;
    if (typeof filename !== "string" || filename.trim().length === 0) {
      throw Object.assign(new Error("filename must be a non-empty string."), {
        code: "INVALID_INPUT",
      });
    }
    if (typeof content !== "string") {
      throw Object.assign(new Error("content must be a string."), {
        code: "INVALID_INPUT",
      });
    }

    const safeName = sanitizeTempFilename(filename);
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "patchdiff-waymark-"));
    const targetPath = path.join(tmpDir, safeName);
    fs.writeFileSync(targetPath, content, { encoding: "utf8", mode: 0o600 });

    const outline = await discoverSymbolsInFile(tmpDir, safeName);
    const rawSymbols = Array.isArray(outline?.symbols) ? outline.symbols : [];
    const filtered = rawSymbols
      .filter((sym) => matchesFilter(sym, { query, kind, symbol_name }))
      .map((sym) => ({
        name: String(sym.name),
        kind: String(sym.kind),
        parent: sym.parent != null ? String(sym.parent) : null,
        signature: sym.signature != null ? String(sym.signature) : null,
        start: {
          line: Number(sym.start.line),
          column: Number(sym.start.column),
        },
        end: {
          line: Number(sym.end.line),
          column: Number(sym.end.column),
        },
      }));

    const response = {
      ok: true,
      waymark_engine_version: WAYMARK_ENGINE_VERSION,
      language: outline?.language ?? null,
      symbols: filtered,
      error: null,
    };
    process.stdout.write(JSON.stringify(response) + "\n");
  } catch (err) {
    const code =
      err && typeof err === "object" && typeof err.code === "string" && err.code.length > 0
        ? err.code
        : "WAYMARK_DISCOVERY_ERROR";
    const message =
      err && typeof err === "object" && typeof err.message === "string"
        ? err.message
        : String(err);
    const response = {
      ok: false,
      waymark_engine_version: WAYMARK_ENGINE_VERSION,
      language: null,
      symbols: [],
      error: {
        code,
        message,
      },
    };
    process.stdout.write(JSON.stringify(response) + "\n");
  } finally {
    if (tmpDir) {
      try {
        fs.rmSync(tmpDir, { recursive: true, force: true });
      } catch {
        // Ignore cleanup errors on exit.
      }
    }
  }
}

await main();
