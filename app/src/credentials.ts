import { invoke } from "@tauri-apps/api/core";

// Backed by the macOS Keychain via the `keyring` Rust crate (lib.rs) — not a
// config file. Python reads the same Keychain item independently when it
// needs the credential for a real API call; there's no handoff between the
// two, both just address the same OS-level store.
export type CredentialKey = "canvas-token" | "openai-key";

export function getCredential(key: CredentialKey): Promise<string | null> {
  return invoke("get_credential", { key });
}

export function setCredential(key: CredentialKey, value: string): Promise<void> {
  return invoke("set_credential", { key, value });
}
