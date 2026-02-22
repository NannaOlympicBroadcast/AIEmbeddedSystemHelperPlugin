import * as path from "path";
import * as vscode from "vscode";
import { sendChat, streamChat, isStreamingEnabled } from "./agentClient";

type WebviewMessage =
  | { type: "userMessage"; text: string }
  | { type: "clearHistory" };

type PanelMessage =
  | { type: "assistantChunk"; text: string }
  | { type: "assistantDone" }
  | { type: "error"; text: string };

export class ChatPanel {
  public static current: ChatPanel | undefined;
  private static readonly viewType = "aiEmbeddedHelperChat";

  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionUri: vscode.Uri;
  private _sessionId: string | undefined;
  private _disposables: vscode.Disposable[] = [];

  private constructor(panel: vscode.WebviewPanel, context: vscode.ExtensionContext) {
    this._panel = panel;
    this._extensionUri = context.extensionUri;

    this._panel.webview.html = this._buildHtml(this._panel.webview);

    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    this._panel.webview.onDidReceiveMessage(
      async (msg: WebviewMessage) => {
        if (msg.type === "clearHistory") {
          this._sessionId = undefined;
          return;
        }
        if (msg.type === "userMessage") {
          await this._handleUserMessage(msg.text);
        }
      },
      null,
      this._disposables
    );
  }

  public static createOrShow(context: vscode.ExtensionContext): void {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (ChatPanel.current) {
      ChatPanel.current._panel.reveal(column);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      ChatPanel.viewType,
      "AI Embedded Helper",
      column ?? vscode.ViewColumn.One,
      {
        enableScripts: true,
        localResourceRoots: [
          vscode.Uri.joinPath(context.extensionUri, "media"),
        ],
      }
    );

    ChatPanel.current = new ChatPanel(panel, context);
  }

  private async _handleUserMessage(text: string): Promise<void> {
    const post = (msg: PanelMessage) =>
      this._panel.webview.postMessage(msg);

    if (isStreamingEnabled()) {
      try {
        const sid = await streamChat(text, this._sessionId, (chunk) => {
          post({ type: "assistantChunk", text: chunk });
        });
        if (sid) {
          this._sessionId = sid;
        }
        post({ type: "assistantDone" });
      } catch (err) {
        post({ type: "error", text: String(err) });
      }
    } else {
      try {
        const resp = await sendChat(text, this._sessionId);
        this._sessionId = resp.session_id;
        post({ type: "assistantChunk", text: resp.reply });
        post({ type: "assistantDone" });
      } catch (err) {
        post({ type: "error", text: String(err) });
      }
    }
  }

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
    <div id="messages"></div>
    <div id="input-row">
      <textarea id="input" rows="3" placeholder="Ask about embedded systems…"></textarea>
      <button id="send-btn">Send</button>
    </div>
    <button id="clear-btn">Clear history</button>
  </div>
  <script nonce="${nonce}" src="${mediaUri("chat.js")}"></script>
</body>
</html>`;
  }

  public dispose(): void {
    ChatPanel.current = undefined;
    this._panel.dispose();
    while (this._disposables.length) {
      const d = this._disposables.pop();
      if (d) {
        d.dispose();
      }
    }
  }
}

function getNonce(): string {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from({ length: 32 }, () =>
    chars.charAt(Math.floor(Math.random() * chars.length))
  ).join("");
}
