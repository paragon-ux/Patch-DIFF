#!/usr/bin/env node
/** Private framed transport. Only public Waymark initialization survives a request. */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";

// Defense-in-depth: redirect console.log/info to console.error so stdout remains clean binary IPC frames
console.log = console.info = (...args) => console.error(...args);

const PROTOCOL = "patchdiff-waymark-worker/1";
const CONTROL_LIMIT = 4096;
const RESULT_LIMIT = 2 * 1024 * 1024;
const keys = (value, names) => value && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === names.sort().join(",");
const fail = (reason = "unspecified") => {
  try {
    fs.writeSync(2, `[worker.mjs fail] ${reason}\n`);
  } catch {}
  process.kill(process.pid, "SIGKILL");
};

function strictControl(raw) {
  const text = new TextDecoder("utf-8", {fatal: true}).decode(raw);
  const value = JSON.parse(text);
  // The parent emits compact JSON. Round-trip equality also rejects duplicate keys,
  // non-finite numbers and alternate encodings in this deliberately tiny protocol.
  if (JSON.stringify(value) !== text) throw new Error("Noncanonical control frame");
  return value;
}

if (!isMainThread) {
  const state = new Int32Array(workerData.state);
  function readExact(size) {
    const data = Buffer.alloc(size);
    let offset = 0;
    while (offset < size) {
      const count = fs.readSync(0, data, offset, size - offset, null);
      if (count === 0) {
        if (Atomics.load(state, 0) !== 1) fail("reader stdin EOF without shutdown state");
        process.exit(0);
      }
      offset += count;
    }
    return data;
  }
  try {
    while (true) {
      const size = readExact(4).readUInt32BE();
      if (!size || size > CONTROL_LIMIT || Atomics.compareExchange(state, 1, 0, 1) !== 0) {
        fail(`reader frame size invalid or atomic CAS failed: size=${size}`);
      }
      parentPort.postMessage(strictControl(readExact(size)));
    }
  } catch (err) { fail(`reader loop threw: ${err?.stack || err}`); }
} else {
  const root = fs.realpathSync(process.argv[2]);
  const stateBuffer = new SharedArrayBuffer(8);
  const state = new Int32Array(stateBuffer);
  const reader = new Worker(new URL(import.meta.url), {workerData: {state: stateBuffer}});
  reader.on("error", (err) => fail(`reader thread error: ${err?.stack || err}`));
  let generation = null;
  let sequence = 0n;
  const core = import("./discovery_core.mjs");
  const here = path.dirname(fileURLToPath(import.meta.url));
  const hash = crypto.createHash("sha256");
  for (const name of ["discovery_core.mjs", "worker.mjs"]) {
    const bytes = fs.readFileSync(path.join(here, name));
    hash.update(name + "\0" + bytes.length + "\0");
    hash.update(bytes);
  }
  const bridgeHash = hash.digest("hex");

  function send(type, id, fields = {}) {
    const message = {protocol: PROTOCOL, type, generation, id, ...fields};
    const raw = Buffer.from(JSON.stringify(message), "utf8");
    if (raw.length > (type === "result" ? RESULT_LIMIT + CONTROL_LIMIT : CONTROL_LIMIT)) {
      fail(`send frame oversized: ${raw.length}`);
    }
    const prefix = Buffer.alloc(4);
    prefix.writeUInt32BE(raw.length);
    Atomics.store(state, 1, 0);
    process.stdout.write(Buffer.concat([prefix, raw]));
  }

  reader.on("message", async (message) => {
    try {
      const common = ["protocol", "type", "generation", "id"];
      if (message.protocol !== PROTOCOL || typeof message.generation !== "string" ||
          !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(message.generation)) {
        fail(`common header check failed: ${JSON.stringify(message)}`);
      }
      const { evaluateDiscovery, WAYMARK_ENGINE_VERSION, recordTiming } = await core;
      if (generation === null) {
        if (message.type !== "hello" || message.id !== "0" ||
            !keys(message, [...common, "engine_version", "bridge_sha256", "owner_pid"]) ||
            message.engine_version !== "4.1.0" ||
            !Number.isSafeInteger(message.owner_pid) || message.owner_pid <= 0 ||
            message.bridge_sha256 !== bridgeHash) {
          fail(`hello handshake failed: msgHash=${message.bridge_sha256} expHash=${bridgeHash} msgPid=${message.owner_pid} curPid=${process.pid}`);
        }
        generation = message.generation;
        send("ready", "0", {engine_version: WAYMARK_ENGINE_VERSION,
          bridge_sha256: bridgeHash, worker_pid: process.pid});
        return;
      }
      if (message.generation !== generation) fail(`generation mismatch: msg=${message.generation} cur=${generation}`);
      if (message.type === "shutdown") {
        if (message.id !== "0" || !keys(message, common)) fail("shutdown invalid keys or id");
        Atomics.store(state, 0, 1);
        send("closed", "0");
        process.stdout.end(() => process.exit(0));
        return;
      }
      if (message.type !== "discover" || !keys(message, [...common, "request_dir", "input_bytes", "input_sha256"]) ||
          typeof message.id !== "string" || !/^[1-9][0-9]{0,19}$/.test(message.id) ||
          BigInt(message.id) <= sequence || BigInt(message.id) > 18446744073709551615n ||
          typeof message.input_bytes !== "string" || !/^[1-9][0-9]*$/.test(message.input_bytes) ||
          typeof message.input_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(message.input_sha256) ||
          typeof message.request_dir !== "string" ||
          !/^request-[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(message.request_dir)) {
        fail(`discover header validation failed: ${JSON.stringify(message)}`);
      }
      sequence = BigInt(message.id);
      const request = path.join(root, message.request_dir);
      if (fs.lstatSync(request).isSymbolicLink() || fs.realpathSync(request) !== request) {
        fail(`request directory symlink/realpath check failed: ${request} realpath=${fs.realpathSync(request)}`);
      }
      const input = path.join(request, "input.json");
      const stat = fs.lstatSync(input);
      if (!stat.isFile() || stat.isSymbolicLink() || fs.realpathSync(input) !== input ||
          BigInt(stat.size) !== BigInt(message.input_bytes)) {
        fail(`input.json stat/realpath check failed: ${input} size=${stat.size} expected=${message.input_bytes} realpath=${fs.realpathSync(input)}`);
      }
      const bytes = fs.readFileSync(input);
      if (crypto.createHash("sha256").update(bytes).digest("hex") !== message.input_sha256) {
        fail("input.json sha256 mismatch");
      }
      const payload = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
      if (!keys(payload, ["filename", "content", "query", "kind", "symbol_name"])) {
        fail(`payload keys mismatch: ${Object.keys(payload)}`);
      }
      const metadata = path.join(request, "performance.json");
      const telemetry = fs.existsSync(metadata) ? JSON.parse(fs.readFileSync(metadata, "utf8")) : {};
      const result = await evaluateDiscovery(payload, request, telemetry);
      const encodeStart = process.hrtime.bigint();
      const resultBytes = Buffer.byteLength(JSON.stringify(result), "utf8") + 1;
      recordTiming("bridge_result_encode", encodeStart, telemetry);
      // Return the same oversized result sentinel through the Python validation path.
      if (resultBytes > RESULT_LIMIT) {
        send("result", message.id, {result: null, result_bytes: resultBytes});
      } else {
        send("result", message.id, {result, result_bytes: resultBytes});
      }
    } catch (err) { fail(`reader on message catch: ${err?.stack || err}`); }
  });
}
