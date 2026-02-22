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
                    this._sessionId = undefined;
                    break;
                case "reloadAgent":
                    await this._reloadAgent();
                    break;
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
            try {
                const sid = await streamChat(
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
                        }
                    }
                );
                if (sid) this._sessionId = sid;
                this.post({ type: "assistantDone" });
            } catch (err) {
                this.post({ type: "error", text: String(err) });
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
  <title>AI Embedded Helper</title>
</head>
<body>
  <div id="chat-container">
    <div id="toolbar">
      <button id="clear-btn">🗑 Clear</button>
      <button id="reload-btn">🔄 Reload Agent</button>
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
