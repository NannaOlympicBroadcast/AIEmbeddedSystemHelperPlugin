import * as vscode from "vscode";
import { sendChat, streamChat, isStreamingEnabled, getBackendUrl } from "./agentClient";
import * as http from "http";
import * as https from "https";

/**
 * Provides the AI Embedded Helper chat panel as a native VSCode sidebar view.
 * Registered against the view id "aiEmbeddedHelper.chatView" declared in package.json.
 */
export class SidebarProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = "aiEmbeddedHelper.chatView";

    private _view?: vscode.WebviewView;
    private _sessionId?: string;
    private _currentAbort?: () => void;  // aborts the active SSE stream
    private _streamGeneration = 0;       // incremented on every new stream; stale handlers check this

    constructor(private readonly _extensionUri: vscode.Uri) { }

    // ---------------------------------------------------------------------------
    // WebviewViewProvider
    // ---------------------------------------------------------------------------

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ): void {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this._extensionUri, "media"),
            ],
        };

        webviewView.webview.html = this._buildHtml(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async (msg) => {
            switch (msg.type) {
                case "clearHistory":
                    // Delete the session on the backend before resetting the ID
                    if (this._sessionId) {
                        fetch(`${getBackendUrl()}/session/${this._sessionId}`, {
                            method: "DELETE",
                        }).catch(() => { /* best-effort */ });
                    }
                    this._sessionId = undefined;
                    break;
                case "stopStream": {
                    // Cancel the live SSE connection immediately
                    this._currentAbort?.();
                    const sidToSeal = this._sessionId;
                    if (sidToSeal) {
                        // Seal the broken ADK turn so the session remains usable
                        // (context is preserved for the next message)
                        fetch(`${getBackendUrl()}/session/${sidToSeal}/seal`, {
                            method: "POST",
                        })
                            .then(r => r.json())
                            .then((_data: unknown) => {
                                // Always keep the session — don't reset context by default.
                                // The user can explicitly "Clear History" if they want a fresh start.
                                this.post({ type: "streamStopped", preserved: true });
                            })
                            .catch(() => {
                                // Network error — keep session_id (optimistic)
                                this.post({ type: "streamStopped", preserved: true });
                            });
                    } else {
                        this.post({ type: "streamStopped", preserved: true });
                    }
                    break;
                }
                case "userMessage":
                    await this._handleUserMessage(msg.text);
                    break;
            }
        });
    }

    /** Focus/reveal the sidebar view. */
    public focus(): void {
        this._view?.show(true);
    }

    // ---------------------------------------------------------------------------
    // Message handling
    // ---------------------------------------------------------------------------

    private post(msg: object): void {
        this._view?.webview.postMessage(msg);
    }

    private async _handleUserMessage(text: string): Promise<void> {
        if (isStreamingEnabled()) {
            // Each invocation gets a unique generation token.  If a newer call
            // starts before this one finishes (e.g. user sends while previous
            // stream is still cleaning up after abort), the older call detects it
            // and exits without touching _currentAbort or posting assistantDone.
            const gen = ++this._streamGeneration;

            const { promise, abort } = streamChat(
                text,
                this._sessionId,
                (chunk) => this.post({ type: "assistantChunk", text: chunk }),
                (toolEvent) => {
                    if (toolEvent.type === "tool_start") {
                        this.post({
                            type: "toolStart",
                            name: toolEvent.name,
                            agent: toolEvent.agent,
                            args: toolEvent.args ?? {},
                        });
                    } else if (toolEvent.type === "tool_result") {
                        this.post({
                            type: "toolResult",
                            name: toolEvent.name,
                            agent: toolEvent.agent,
                            result: toolEvent.result ?? "",
                        });
                    } else if (toolEvent.type === "form") {
                        this.post({ ...toolEvent });
                    }
                }
            );
            this._currentAbort = abort;
            this.post({ type: "streamStarted" });
            try {
                const sid = await promise;
                if (gen !== this._streamGeneration) { return; } // superseded by newer stream
                if (sid) { this._sessionId = sid; }
                this.post({ type: "assistantDone" });
            } catch (err) {
                if (gen !== this._streamGeneration) { return; } // superseded
                this.post({ type: "error", text: String(err) });
            } finally {
                if (gen === this._streamGeneration) {
                    this._currentAbort = undefined;
                }
            }
        } else {
            try {
                const resp = await sendChat(text, this._sessionId);
                this._sessionId = resp.session_id;
                this.post({ type: "assistantChunk", text: resp.reply });
                this.post({ type: "assistantDone" });
            } catch (err) {
                this.post({ type: "error", text: String(err) });
            }
        }
    }

    private async _reloadAgent(): Promise<void> {
        const url = new URL("/reload", getBackendUrl());
        await new Promise<void>((resolve) => {
            const mod = url.protocol === "https:" ? https : http;
            const req = mod.request(url, { method: "POST" }, (res) => {
                res.resume();
                res.on("end", resolve);
            });
            req.on("error", resolve);
            req.end();
        });
        this.post({ type: "agentReloaded" });
    }

    // ---------------------------------------------------------------------------
    // HTML
    // ---------------------------------------------------------------------------

    private _buildHtml(webview: vscode.Webview): string {
        const mediaUri = (file: string) =>
            webview.asWebviewUri(
                vscode.Uri.joinPath(this._extensionUri, "media", file)
            );

        const nonce = getNonce();

        return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none';
             style-src ${webview.cspSource} 'nonce-${nonce}';
             script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${mediaUri("chat.css")}">
  <title>Dream River</title>
</head>
<body>
  <div id="chat-container">
    <div id="toolbar">
      <button id="clear-btn">🗑 Clear</button>
      <button id="stop-btn" disabled>⏹ Stop</button>
    </div>
    <div id="messages"></div>
    <div id="input-row">
      <textarea id="input" rows="3" placeholder="Ask about embedded systems…"></textarea>
      <button id="send-btn">Send</button>
    </div>
  </div>
  <script nonce="${nonce}" src="${mediaUri("chat.js")}"></script>
</body>
</html>`;
    }
}

function getNonce(): string {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    return Array.from({ length: 32 }, () =>
        chars.charAt(Math.floor(Math.random() * chars.length))
    ).join("");
}
