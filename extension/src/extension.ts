import * as vscode from "vscode";
import { ChatPanel } from "./panel";
import { SidebarProvider } from "./sidebarProvider";
import { BackendManager } from "./backendManager";

let backendManager: BackendManager | undefined;

export async function activate(
  context: vscode.ExtensionContext
): Promise<void> {
  // Start the bundled backend process
  backendManager = new BackendManager(context);
  try {
    await backendManager.start();
  } catch (err) {
    vscode.window.showWarningMessage(
      `AI Embedded Helper: Backend start issue — ${err}. ` +
      "You can configure an external backend in settings."
    );
  }

  // Watch for settings changes and restart backend automatically
  const configWatcher = backendManager.registerConfigWatcher();

  // Register the sidebar webview provider
  const sidebarProvider = new SidebarProvider(context.extensionUri);
  const sidebarView = vscode.window.registerWebviewViewProvider(
    SidebarProvider.viewType,
    sidebarProvider,
    { webviewOptions: { retainContextWhenHidden: true } }
  );

  // Register the chat command — focuses the sidebar view (or opens panel as fallback)
  const openChat = vscode.commands.registerCommand(
    "aiEmbeddedHelper.openChat",
    () => {
      // Reveal the sidebar view; also open legacy panel on explicit command
      vscode.commands.executeCommand("aiEmbeddedHelper.chatView.focus");
    }
  );

  context.subscriptions.push(openChat, sidebarView, configWatcher);
}

export async function deactivate(): Promise<void> {
  if (backendManager) {
    await backendManager.stop();
    backendManager = undefined;
  }
}
