import * as http from "http";
import * as https from "https";
import * as vscode from "vscode";

export interface ChatResponse {
  session_id: string;
  reply: string;
}

function getBackendUrl(): string {
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

/** GET /chat/stream – calls onChunk for each SSE chunk, resolves with the session ID when done. */
export async function streamChat(
  message: string,
  sessionId: string | undefined,
  onChunk: (chunk: string) => void
): Promise<string | undefined> {
  const url = new URL("/chat/stream", getBackendUrl());
  url.searchParams.set("message", message);
  if (sessionId) {
    url.searchParams.set("session_id", sessionId);
  }

  return new Promise((resolve, reject) => {
    const mod = url.protocol === "https:" ? https : http;
    const req = mod.request(url, { method: "GET" }, (res) => {
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
            const payload = JSON.parse(line.slice(6)) as {
              chunk: string;
              done: boolean;
            };
            if (payload.done) {
              resolve(returnedSessionId);
              return;
            }
            if (payload.chunk) {
              onChunk(payload.chunk);
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      });
      res.on("end", () => resolve(returnedSessionId));
      res.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

export { isStreamingEnabled };
