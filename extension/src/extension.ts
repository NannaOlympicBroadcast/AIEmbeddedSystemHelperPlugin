import * as vscode from "vscode";
import { ChatPanel } from "./panel";

export function activate(context: vscode.ExtensionContext): void {
  const openChat = vscode.commands.registerCommand(
    "aiEmbeddedHelper.openChat",
    () => {
      ChatPanel.createOrShow(context);
    }
  );

  context.subscriptions.push(openChat);
}

export function deactivate(): void {}
