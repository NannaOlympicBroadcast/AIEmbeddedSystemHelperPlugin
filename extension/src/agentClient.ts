import * as http from "http";
import * as https from "https";
import * as vscode from "vscode";

export interface ChatResponse {
  session_id: string;
  reply: string;
}

export function getBackendUrl(): string {
  return vscode.workspace
    .getConfiguration("aiEmbeddedHelper")
    .get<string>("backendUrl", "http://127.0.0.1:8000");
}

function isStreamingEnabled(): boolean {
  return vscode.workspace
    .getConfiguration("aiEmbeddedHelper")
    .get<boolean>("streamingEnabled", true);
}

/** POST /chat – returns full reply. */
export async function sendChat(
  message: string,
  sessionId?: string
): Promise<ChatResponse> {
  const url = new URL("/chat", getBackendUrl());
  const body = JSON.stringify({ message, session_id: sessionId ?? null });

  return new Promise((resolve, reject) => {
    const mod = url.protocol === "https:" ? https : http;
    const req = mod.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk: Buffer) => (data += chunk.toString()));
        res.on("end", () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`Backend error ${res.statusCode}: ${data}`));
            return;
          }
          try {
            resolve(JSON.parse(data) as ChatResponse);
          } catch {
            reject(new Error(`Failed to parse backend response: ${data}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

/** Parsed SSE tool event from the backend. */
export interface ToolEvent {
  type: "tool_start" | "tool_result";
  name: string;
  agent: string;
  args?: Record<string, unknown>;
  result?: string;
}

/** Parsed SSE form event from the backend. */
export interface FormEvent {
  type: "form";
  form_id: string;
  title: string;
  description: string;
  buttons: Array<{ label: string; value: string }>;
  fields: Array<{ name: string; label: string; placeholder?: string }>;
}

export type AgentEvent = ToolEvent | FormEvent;

/** GET /chat/stream – calls onChunk for text, onTool for tool/form events.
 *  Returns both the promise and an abort() function that terminates the stream
 *  immediately without triggering an error in the UI. */
export function streamChat(
  message: string,
  sessionId: string | undefined,
  onChunk: (chunk: string) => void,
  onTool?: (event: AgentEvent) => void
): { promise: Promise<string | undefined>; abort: () => void } {
  const url = new URL("/chat/stream", getBackendUrl());
  url.searchParams.set("message", message);
  if (sessionId) {
    url.searchParams.set("session_id", sessionId);
  }

  let aborted = false;
  let req: ReturnType<typeof http.request> | undefined;

  const promise = new Promise<string | undefined>((resolve, reject) => {
    const mod = url.protocol === "https:" ? https : http;
    req = mod.request(url, { method: "GET" }, (res) => {
      const returnedSessionId =
        (res.headers["x-session-id"] as string | undefined) ?? sessionId;
      let buffer = "";
      res.on("data", (chunk: Buffer) => {
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) {
            continue;
          }
          try {
            const payload = JSON.parse(line.slice(6));
            const payloadType = payload.type ?? "text";
            if (payloadType === "text") {
              if (payload.done) {
                resolve(returnedSessionId);
                return;
              }
              if (payload.chunk) {
                onChunk(payload.chunk);
              }
            } else if (
              (payloadType === "tool_start" ||
                payloadType === "tool_result" ||
                payloadType === "form") &&
              onTool
            ) {
              onTool(payload as AgentEvent);
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      });
      res.on("end", () => resolve(returnedSessionId));
      res.on("error", (err) => {
        if (aborted) { resolve(undefined); } else { reject(err); }
      });
    });
    req.on("error", (err) => {
      const code = (err as NodeJS.ErrnoException).code ?? "";
      if (aborted || code === "ECONNRESET" || code === "ECONNABORTED") {
        resolve(undefined);
      } else {
        reject(err);
      }
    });
    req.end();
  });

  return {
    promise,
    abort: () => { aborted = true; req?.destroy(); },
  };
}

export { isStreamingEnabled };
