/**
 * BackendManager — manages the lifecycle of the bundled Python backend process.
 *
 * On extension activation:
 *   1. Locate the platform-specific executable in resources/bin/
 *   2. Spawn it as a child process with user-configured env vars
 *   3. Poll /health until the server is ready
 *
 * On extension deactivation:
 *   1. Gracefully terminate the child process
 */

import * as cp from "child_process";
import * as http from "http";
import * as path from "path";
import * as vscode from "vscode";

const HEALTH_POLL_INTERVAL_MS = 500;
const HEALTH_POLL_TIMEOUT_MS = 30_000;

export class BackendManager {
    private process: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;
    private port: number = 8000;
    private configWatcher: vscode.Disposable | undefined;

    constructor(private readonly context: vscode.ExtensionContext) {
        this.outputChannel = vscode.window.createOutputChannel(
            "Dream River Backend"
        );
    }

    /** Start the bundled backend or skip if the user configured an external one. */
    async start(): Promise<void> {
        const cfg = vscode.workspace.getConfiguration("aiEmbeddedHelper");
        const useExternal = cfg.get<boolean>("useExternalBackend", false);

        if (useExternal) {
            this.outputChannel.appendLine(
                "[BackendManager] Using external backend — skipping built-in start."
            );
            return;
        }

        const executablePath = this.resolveExecutable();
        if (!executablePath) {
            vscode.window.showErrorMessage(
                "AI Embedded Helper: Could not find bundled backend executable. " +
                "Please enable 'Use External Backend' in settings and start the backend manually."
            );
            return;
        }

        const env = this.buildEnv(cfg);
        this.port = parseInt(env.SERVER_PORT || "8000", 10);

        this.outputChannel.appendLine(
            `[BackendManager] Starting backend: ${executablePath}`
        );
        this.outputChannel.appendLine(
            `[BackendManager] Port: ${this.port}`
        );

        this.process = cp.spawn(executablePath, [], {
            env: { ...process.env, ...env },
            cwd: path.dirname(executablePath),
            stdio: ["ignore", "pipe", "pipe"],
        });

        this.process.stdout?.on("data", (data: Buffer) => {
            this.outputChannel.append(data.toString());
        });

        this.process.stderr?.on("data", (data: Buffer) => {
            this.outputChannel.append(data.toString());
        });

        this.process.on("exit", (code: number | null) => {
            this.outputChannel.appendLine(
                `[BackendManager] Backend exited with code ${code}`
            );
            this.process = undefined;
        });

        // Wait for the server to become healthy
        await this.waitForHealth();
    }

    /** Gracefully stop the backend process.
     * @param keepWatcher If true, do NOT dispose the config watcher (used during restart).
     */
    async stop(keepWatcher = false): Promise<void> {
        if (!keepWatcher) {
            this.configWatcher?.dispose();
            this.configWatcher = undefined;
        }
        if (!this.process) {
            this.outputChannel.appendLine("[BackendManager] No process to stop.");
            return;
        }
        this.outputChannel.appendLine("[BackendManager] Stopping backend...");

        return new Promise<void>((resolve) => {
            if (!this.process) {
                resolve();
                return;
            }

            const timeout = setTimeout(() => {
                this.process?.kill("SIGKILL");
                resolve();
            }, 5_000);

            this.process.on("exit", () => {
                clearTimeout(timeout);
                this.outputChannel.appendLine("[BackendManager] Backend process exited.");
                resolve();
            });

            // On Windows, SIGTERM is not well-supported; use taskkill for graceful shutdown
            if (process.platform === "win32" && this.process.pid) {
                cp.exec(`taskkill /pid ${this.process.pid} /T /F`, () => { });
            } else {
                this.process.kill("SIGTERM");
            }
        });
    }

    /**
     * Register a VSCode config watcher — whenever the user changes any
     * `aiEmbeddedHelper.*` setting, the backend is restarted automatically
     * so the new API key / model / URL takes effect immediately.
     */
    registerConfigWatcher(): vscode.Disposable {
        this.configWatcher?.dispose();
        this.configWatcher = vscode.workspace.onDidChangeConfiguration(async (e) => {
            if (!e.affectsConfiguration("aiEmbeddedHelper")) {
                return;
            }
            this.outputChannel.appendLine(
                "[BackendManager] Settings changed — applying new config..."
            );

            const cfg = vscode.workspace.getConfiguration("aiEmbeddedHelper");
            const useExternal = cfg.get<boolean>("useExternalBackend", false);

            if (useExternal) {
                // For external backends, call the /reload-config endpoint
                // to hot-reload settings without restarting the process.
                const backendUrl = this.getBackendUrl();
                const env = this.buildEnv(cfg);
                try {
                    const http = require("http");
                    const url = new URL(`${backendUrl}/reload-config`);
                    const body = JSON.stringify({
                        LITELLM_API_KEY: env.LITELLM_API_KEY || "",
                        LITELLM_API_BASE: env.LITELLM_API_BASE || "",
                        LITELLM_MODEL: env.LITELLM_MODEL || "",
                        TAVILY_API_KEY: env.TAVILY_API_KEY || "",
                        ELECTERM_MCP_URL: env.ELECTERM_MCP_URL || "",
                    });
                    const req = http.request(
                        {
                            hostname: url.hostname,
                            port: url.port,
                            path: url.pathname,
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json",
                                "Content-Length": Buffer.byteLength(body),
                            },
                        },
                        (res: any) => {
                            if (res.statusCode === 200) {
                                vscode.window.showInformationMessage(
                                    "AI Embedded Helper: Config reloaded successfully."
                                );
                                this.outputChannel.appendLine(
                                    "[BackendManager] External backend config reloaded ✓"
                                );
                            } else {
                                vscode.window.showWarningMessage(
                                    `AI Embedded Helper: Config reload failed (HTTP ${res.statusCode}). Please restart the backend manually.`
                                );
                            }
                        }
                    );
                    req.on("error", () => {
                        vscode.window.showWarningMessage(
                            "AI Embedded Helper: Could not reach backend for config reload. Please restart it manually."
                        );
                    });
                    req.write(body);
                    req.end();
                } catch {
                    vscode.window.showWarningMessage(
                        "AI Embedded Helper: Config reload request failed. Please restart the backend manually."
                    );
                }
            } else {
                // For bundled backends, do a full restart to pick up new env vars
                vscode.window.showInformationMessage(
                    "AI Embedded Helper: Settings changed, restarting backend..."
                );
                this.outputChannel.appendLine(
                    "[BackendManager] Config change detected — stopping current backend..."
                );
                await this.stop(/* keepWatcher */ true);
                // On Windows, the OS may not release the port immediately after
                // taskkill.  Wait a short time before starting the new process.
                this.outputChannel.appendLine(
                    "[BackendManager] Waiting for port release..."
                );
                await new Promise((r) => setTimeout(r, 1500));
                this.outputChannel.appendLine(
                    "[BackendManager] Starting backend with new settings..."
                );
                try {
                    await this.start();
                    this.outputChannel.appendLine(
                        "[BackendManager] Backend restarted with new settings ✓"
                    );
                    vscode.window.showInformationMessage(
                        "AI Embedded Helper: Backend restarted successfully."
                    );
                } catch (err) {
                    this.outputChannel.appendLine(
                        `[BackendManager] Backend restart FAILED: ${err}`
                    );
                    vscode.window.showErrorMessage(
                        `AI Embedded Helper: Backend restart failed — ${err}. ` +
                        "Try reloading the window (Ctrl+Shift+P → Reload Window)."
                    );
                }
            }
        });
        return this.configWatcher;
    }

    /** Get the backend URL for the agent client to connect to. */
    getBackendUrl(): string {
        const cfg = vscode.workspace.getConfiguration("aiEmbeddedHelper");
        const useExternal = cfg.get<boolean>("useExternalBackend", false);
        if (useExternal) {
            return cfg.get<string>("backendUrl", "http://127.0.0.1:8000");
        }
        return `http://127.0.0.1:${this.port}`;
    }

    // ── Private helpers ─────────────────────────────────────────────────────

    private resolveExecutable(): string | undefined {
        const resourcesDir = path.join(
            this.context.extensionPath,
            "resources",
            "bin"
        );

        let execName: string;
        const plat = process.platform;
        switch (plat) {
            case "win32":
                execName = "backend-win.exe";
                break;
            case "darwin":
                execName = "backend-darwin";
                break;
            default:
                execName = "backend-linux";
        }

        const fullPath = path.join(resourcesDir, execName);
        try {
            const fs = require("fs");
            if (fs.existsSync(fullPath)) {
                return fullPath;
            }
        } catch {
            // fall through
        }
        return undefined;
    }

    private buildEnv(
        cfg: vscode.WorkspaceConfiguration
    ): Record<string, string> {
        const env: Record<string, string> = {};

        // LLM config from VSCode settings
        const apiKey = cfg.get<string>("apiKey", "");
        const apiBase = cfg.get<string>("apiBase", "https://api.openai.com/v1");
        const model = cfg.get<string>("model", "openai/gpt-4o");
        const tavilyKey = cfg.get<string>("tavilyApiKey", "");
        const electermMcpUrl = cfg.get<string>("electermMcpUrl", "");

        if (apiKey) { env.LITELLM_API_KEY = apiKey; }
        if (apiBase) { env.LITELLM_API_BASE = apiBase; }
        if (model) { env.LITELLM_MODEL = model; }
        if (tavilyKey) { env.TAVILY_API_KEY = tavilyKey; }
        if (electermMcpUrl) { env.ELECTERM_MCP_URL = electermMcpUrl; }

        env.SERVER_HOST = "127.0.0.1";
        env.SERVER_PORT = String(this.port);

        // ── Project-specific data directory ──────────────────────────────────
        // Prefer: <workspace_root>/.dream-river/data  (each project has its own data)
        // Fallback: VS Code global storage (cross-project, always writable)
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (workspaceFolder) {
            env.PROJECT_MEMORY_DIR = path.join(workspaceFolder, ".dream-river", "data");
        } else {
            env.PROJECT_MEMORY_DIR = path.join(
                this.context.globalStorageUri.fsPath, "data"
            );
        }
        this.outputChannel.appendLine(
            `[BackendManager] Data dir: ${env.PROJECT_MEMORY_DIR}`
        );

        return env;
    }

    private async waitForHealth(): Promise<void> {
        const start = Date.now();
        const url = `http://127.0.0.1:${this.port}/health`;

        return new Promise<void>((resolve, reject) => {
            const poll = () => {
                if (Date.now() - start > HEALTH_POLL_TIMEOUT_MS) {
                    reject(
                        new Error(
                            "Backend did not become healthy within " +
                            HEALTH_POLL_TIMEOUT_MS / 1000 +
                            "s"
                        )
                    );
                    return;
                }

                http
                    .get(url, (res: http.IncomingMessage) => {
                        if (res.statusCode === 200) {
                            this.outputChannel.appendLine(
                                "[BackendManager] Backend is healthy ✓"
                            );
                            resolve();
                        } else {
                            setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
                        }
                    })
                    .on("error", () => {
                        setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
                    });
            };

            // Give the process a moment to start
            setTimeout(poll, HEALTH_POLL_INTERVAL_MS);
        });
    }
}
