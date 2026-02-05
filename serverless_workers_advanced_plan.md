# Next-Level Serverless Worker Layer for Cloud Terminal Platform

## Motivation

Building on the existing `serverless_workers_technical_plan.md`, the goal is to evolve the current sandbox/runtime architecture into: (1) a modular, "free" serverless-use case that feels like a Cloudflare Workers + Sandbox SDK clone, (2) a hardened preview & always-on surface, and (3) a fallback/resilience catalog that can transitively spin up containers or Firecracker guests whenever the lightweight runtime reaches its limits.

## 1. Layered Architecture Overview

```
            +-------------------------+
            | External Client (CLI /  |
            |   Browser / Agent)      |
            +------------+------------+
                         |
                         v
                 [Ingress FastAPI Router]
                         |
                         v
+----------------+   +--------------------+   +------------------+
| Sandbox Worker |<->| Command Scheduler  |<->| Preview URL Layer |
|   (WASM DO)    |   |  (v2 of serverless-shell) | (HTTP + WS proxies) |
+----------------+   +--------------------+   +------------------+
         |                     |                      |
         v                     v                      v
   [Virtual FS]          [Event Recorder]        [Streaming Logs]
         |                     |                      |
    {R2, KV, disk}        Db + KV / Kafka      Reverse proxy cache
```

### Key Ideas

1. **Sandbox Worker (WASM-first Durable Object)**: Each worker maintains a `VirtualFS`, `WasmEngine`, and bound `PreviewPort` map. It exposes a thin RPC interface for command execution, file operations, snapshotting, and preview registration.
2. **Command Scheduler**: A Rust/Bun/TS scheduler receives CLI requests (via HTTP, queue, or WebSocket), enforces quotas, and routes them to a worker. It also spins up a fallback Docker/Firecracker container when CPU/memory limits or unsupported binaries are detected.
3. **Preview URL Layer**: The existing `/preview/<id>` router is replaced with a multiplexer that can serve HTTP + WebSocket traffic either directly from the worker (fast path) or proxy through a container-based HTTP server (fallback path).
4. **Modular "Free Serverless" Use Case**: Create a reusable module (`serverless-workers-sdk`) that exports the public API, preview registration helpers, and CLI/integration support for embedding the runtime in new products.

## 2. Free Serverless Use Case Module (`serverless-workers-sdk`)

> **Goal**: let third-party developers deploy a per-user sandbox without using expensive containers. The module should wrap the sandbox worker, provide CLI-like helpers, and optionally mount fallback clients.

### Folder Layout

```
serverless-workers-sdk/
├─ index.ts             # public API mirroring Cloudflare Sandbox SDK
├─ worker-client.ts     # HTTP/WebSocket clients for preview + exec
├─ runtime-proxy.ts     # helpers used by sandbox workers
└─ example-app/
    └─ handler.ts       # sample worker showing preview + exec
```

### Code example: public API (diff)

```diff
@@ -0,0 +1,62 @@
+// serverless-workers-sdk/index.ts
+import { fetchJson } from './worker-client';
+
+export type SandboxExecResult = {
+  stdout: string;
+  stderr: string;
+  exitCode: number;
+  success: boolean;
+};
+
+export class SandboxClient {
+  constructor(private baseUrl: string, private apiKey?: string) {}
+
+  async exec(command: string, args: string[] = []): Promise<SandboxExecResult> {
+    return fetchJson(`${this.baseUrl}/sandboxes/exec`, {
+      method: 'POST',
+      headers: this.headers,
+      body: JSON.stringify({ command, args }),
+    });
+  }
+
+  async write(path: string, data: string): Promise<void> {
+    await fetch(`${this.baseUrl}/sandboxes/files`, {
+      method: 'PUT',
+      headers: this.headers,
+      body: JSON.stringify({ path, data }),
+    });
+  }
+
+  async preview(port: number): Promise<string> {
+    const res = await fetchJson(`${this.baseUrl}/preview/register`, {
+      method: 'POST',
+      headers: this.headers,
+      body: JSON.stringify({ port }),
+    });
+    return res.url;
+  }
+
+  private get headers() {
+    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
+    if (this.apiKey) headers['Authorization'] = `Bearer ${this.apiKey}`;
+    return headers;
+  }
+}
```

### Runtime hook (used inside sandbox workers)

```ts
+// serverless-workers-sdk/runtime-proxy.ts
+export async function registerPreviewPort(port: number, sandboxId: string) {
+  // Register port in preview registry, returns the path used by router
+  const url = new URL(`/preview/${sandboxId}/${port}`, env.BASE_URL!);
+  await env.PREVIEW_REGISTRY.put(`${sandboxId}:${port}`, url.toString());
+  return url.toString();
+}
```

This module can be published as an NPM package or consumed by other services sitting on `serverless-shell/lib`.

## 3. Cloudflare Worker Sandbox SDK Emulation Layer

### Differences to mimic

| Feature | Implementation
| --- | ---
| `getSandbox(env, id)` | Durable object stub factory returns worker state with `exec`, `serve`, `writeFile`
| Streaming command output | WebSocket channel relays `stdout`/`stderr` with incremental events
| Preview URLs | `ingress/preview.ts` rewrites to `/preview/<sandbox>/<port>`
| Persistent mounts | `VirtualFS` mounts to R2/Bucket, optionally using `storage_objects` binding
| Background processes | Async loops spawn in worker, heartbeat keeps sandbox warm

### Integration plan

1. **Expose a `sandbox.exec(command)` API** that sends command + args to `SandboxRuntime.exec`. Use message queueing for streaming outputs.
2. **Allow background workers**: new `background_process.ts` that accepts `start`, `stop`, `status`, backed by the same runtime scheduler used by serverless-shell.
3. **Expose `sandbox.preview(port)`** via the new preview registry service in the `serverless-workers-sdk`.
4. **Support `sandbox.mount(bucket)`** hooking R2 / S3 through `VirtualFS.mount()` that lazily fetches objects.
5. **Always-on semantics**: implement `keepAlive()` inside `SandboxRuntime` that sets recurring alarms / heartbeats. When running on container fallback, this maps to a systemd timer.

## 4. Advanced Fallbacks

| Scenario | Fallback | Trigger | Implementation notes |
| --- | --- | --- | --- |
| WASM runtime exhausts memory | Firecracker microVM | Memory > 80MB, command flagged `requires-native` | Use snapshot to pre-load FS; route traffic over HTTP reverse proxy from preview router to Firecracker webserver.
| Unsupported binary (e.g. gcc) | Container via `serverless-shell/lambdas` | Command whitelist check fails | Router reroutes CLI + preview to Docker service using ephemeral port mappings.
| High concurrent preview load | CDN + Edge cache | Preview request throughput > 500 rps | Put NGINX/Envoy cache in front, configure TTL per resource via manifest.
| Networking (eg. outbound DB) | Use proxy service | Attempt to dial blocked host | Intercept via `NetworkSecurity.restricted_socket` and forward through proxy (with ACLs).|
| Always-on requirement | Persistent DO + snapshot heartbeats | Heartbeat triggered by scheduler | Keep state warm; fallback safely to snapshot/restore if DO is paused.

## 5. Operational Enhancements

- **Event Sourcing**: send every command/event (exec, fs op, preview registration) to `EventRecorder` (Kafka/Redis stream). This enables audit, rebuild, and versioned rollback if necessary.
- **Quota enforcement**: `QuotaManager` uses KV to track CPU time / exec count per sandbox, exposing `/quota/check` API.
- **Security sandboxing**: tighten to per-path ACL + WASM Fuel. Provide `sandbox.allowlist(['python','node'])` for each user with permissioning logic.
- **Observability**: export `SandboxMetrics` (exec latency, snapshot size, preview hits) to `/metrics` endpoint for Prometheus.

## 6. Implementation Roadmap

1. **Create `serverless-workers-sdk` package** and hook into `serverless-shell/lib/shell-backend-stack.ts` so CLI commands can `import { SandboxClient }`.
2. **Refactor preview router** to consult a central registry (R2 or Workers KV) and proxy to whichever runtime (WASM or fallback container) holds the port.
3. **Extend `SandboxRuntime`** with `keepAlive()`, `backgroundJobs`, and `mountPersistence()` features, plus better snapshot + quota telemetry.
4. **Wire fallback orchestrator**: use existing `container_fallback.py` + `serverless-shell/lambdas/*` to spawn Firecracker/Container, keep state sync with WASM runtime via `snapshot_api.py`.
5. **Document new use case** in `serverless_workers_advanced_plan.md`, referencing `FALLBACK_METHODS.md` and `CIDD.md` for controls.

The result is a hardened serverless worker tier that feels like a locally hosted Cloudflare Sandbox SDK, with a companion free-use case module, streaming preview surface, and resilient fallback stack.