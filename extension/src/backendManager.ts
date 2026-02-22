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
            "AI Embedded Helper Backend"
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

    /** Gracefully stop the backend process. */
    async stop(): Promise<void> {
        this.configWatcher?.dispose();
        this.configWatcher = undefined;
        if (!this.process) {
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
                "[BackendManager] Settings changed — restarting backend to apply new config..."
            );
            vscode.window.showInformationMessage(
                "AI Embedded Helper: Settings changed, restarting backend..."
            );
            await this.stop();
            await this.start();
            this.outputChannel.appendLine(
                "[BackendManager] Backend restarted with new settings."
            );
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

        if (apiKey) { env.LITELLM_API_KEY = apiKey; }
        if (apiBase) { env.LITELLM_API_BASE = apiBase; }
        if (model) { env.LITELLM_MODEL = model; }
        if (tavilyKey) { env.TAVILY_API_KEY = tavilyKey; }

        env.SERVER_HOST = "127.0.0.1";
        env.SERVER_PORT = String(this.port);

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
