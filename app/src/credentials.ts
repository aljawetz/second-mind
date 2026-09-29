import { invoke } from "@tauri-apps/api/core";

// Backed by the macOS Keychain via the `keyring` Rust crate (lib.rs) — not a
// config file. Python reads the same Keychain item independently when it
// needs the credential for a real API call; there's no handoff between the
// two, both just address the same OS-level store.
export type CredentialKey = "canvas-token" | "openai-key" | "deepseek-key" | "github-copilot-token";

// Mirrors backend/providers.py: which model provider answers, chosen during
// onboarding and saved as config.json's llm_provider. Each keeps its key in
// its own Keychain item, so switching back doesn't lose the other key.
export type LlmProvider = "openai" | "deepseek" | "copilot";

export const LLM_PROVIDERS: Record<
  LlmProvider,
  { name: string; credential: CredentialKey; keyLabel: string; keyHint: string }
> = {
  openai: { name: "OpenAI", credential: "openai-key", keyLabel: "OpenAI API key", keyHint: "platform.openai.com/api-keys" },
  deepseek: {
    name: "DeepSeek",
    credential: "deepseek-key",
    keyLabel: "DeepSeek API key",
    keyHint: "platform.deepseek.com/api_keys",
  },
  // Billed to the student's own Copilot plan (premium requests).
  copilot: {
    name: "GitHub Copilot",
    credential: "github-copilot-token",
    keyLabel: "GitHub token",
    keyHint:
      "GitHub → Settings → Developer settings → Fine-grained tokens: owner = your account, Account permission Copilot Requests. Needs a Copilot plan.",
  },
};

export function getCredential(key: CredentialKey): Promise<string | null> {
  return invoke("get_credential", { key });
}

export function setCredential(key: CredentialKey, value: string): Promise<void> {
  return invoke("set_credential", { key, value });
}
