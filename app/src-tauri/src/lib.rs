// Credential storage: this app is the only process that touches the macOS
// Keychain. The backend used to read the same items itself, which made macOS
// ask about two programs — and "Always Allow" for an ad-hoc signed program
// only lasts until it's rebuilt, so students kept seeing prompts. Now the
// backend gets every stored credential on stdin at launch and each change
// after (backend/credentials.py), and hands back what it obtains itself
// (Sign in with GitHub) as a CREDENTIAL_SAVE_PREFIX line on stdout.
const CREDENTIAL_SERVICE: &str = "com.secondmind.app";
// Every item the app keeps — credentials.ts's CredentialKey.
const CREDENTIAL_KEYS: [&str; 4] = ["canvas-token", "openai-key", "deepseek-key", "github-copilot-token"];
const CREDENTIAL_SAVE_PREFIX: &str = "sm-credential:";

fn read_credential(key: &str) -> Result<Option<String>, String> {
    use keyring::v1::Entry;
    let entry = Entry::new(CREDENTIAL_SERVICE, key).map_err(|e| e.to_string())?;
    match entry.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::v1::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

fn save_credential(key: &str, value: &str) -> Result<(), String> {
    use keyring::v1::Entry;
    let entry = Entry::new(CREDENTIAL_SERVICE, key).map_err(|e| e.to_string())?;
    entry.set_password(value).map_err(|e| e.to_string())
}

// A line the backend printed after CREDENTIAL_SAVE_PREFIX: {key: value}.
// Only known keys are saved, and nothing here logs a value.
fn save_credentials_from_backend(json: &str) {
    let Ok(update) = serde_json::from_str::<std::collections::HashMap<String, String>>(json) else {
        eprintln!("[credentials] ignored a malformed save request from the backend");
        return;
    };
    for (key, value) in update {
        if !CREDENTIAL_KEYS.contains(&key.as_str()) {
            eprintln!("[credentials] ignored unknown credential '{key}' from the backend");
        } else if let Err(e) = save_credential(&key, &value) {
            eprintln!("[credentials] couldn't save '{key}' to the Keychain: {e}");
        }
    }
}

#[tauri::command]
fn get_credential(key: String) -> Result<Option<String>, String> {
    read_credential(&key)
}

#[tauri::command]
fn set_credential(backend: tauri::State<Backend>, key: String, value: String) -> Result<(), String> {
    save_credential(&key, &value)?;
    backend.send_credentials(&[(key, value)].into_iter().collect())
}

// Held for the app's whole lifetime. Dropping the CommandChild closes the
// write end of the backend's stdin, which the backend treats as "the app
// is gone" and exits (main.py's _exit_when_app_closes) — so the child
// must live in managed state, not a local that dies at the end of setup.
// The OS closes that same pipe when this process ends for any reason
// (quit, crash, force quit), which is what stops the backend outliving
// the app and holding port 8756 for the next launch.
struct Backend {
    child: std::sync::Mutex<tauri_plugin_shell::process::CommandChild>,
    instance_token: String,
}

impl Backend {
    // One JSON line on the backend's stdin (backend/credentials.py).
    fn send_credentials(&self, credentials: &std::collections::HashMap<String, String>) -> Result<(), String> {
        let mut line = serde_json::to_vec(credentials).map_err(|e| e.to_string())?;
        line.push(b'\n');
        self.child
            .lock()
            .map_err(|e| e.to_string())?
            .write(&line)
            .map_err(|e| format!("couldn't pass the credential to the backend: {e}"))
    }
}

#[tauri::command]
fn backend_instance_token(backend: tauri::State<Backend>) -> String {
    backend.instance_token.clone()
}

// Identity, not a secret: only has to differ between launches so the
// frontend can reject a stale backend answering on 8756. RandomState is
// seeded randomly per process, which avoids pulling in a rand crate.
fn new_instance_token() -> String {
    use std::hash::{BuildHasher, Hasher};
    let mut hasher = std::collections::hash_map::RandomState::new().build_hasher();
    hasher.write_u128(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or_default(),
    );
    format!("{:016x}", hasher.finish())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri::Manager;
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Spawn the Python backend when the app starts, started/stopped
            // with the app (overview.md §1; stopping is the Backend state
            // above). Stdout/stderr are logged, not wired to the frontend.
            //
            // It's a PyInstaller onedir build (backend/sm-backend.spec says
            // why: ~2s startup instead of ~35s) — a folder, so not an
            // externalBin/sidecar, which can only be a single file. Nor a
            // tauri.conf.json resource: Tauri's resource copier fails on the
            // folder's symlinks ("Not a directory (os error 20)"), and
            // flattening them would duplicate ~160 MB of dylibs and risk
            // loading one library twice. So: dev runs it in place from
            // binaries/, and a release gets it copied into
            // Contents/Resources/ by scripts/package-macos.sh (ditto keeps
            // the symlinks) before the bundle is re-signed.
            //
            // EXE_SUFFIX is ".exe" on Windows (PyInstaller's output name
            // there) and empty elsewhere.
            let backend_exe = format!("sm-backend{}", std::env::consts::EXE_SUFFIX);
            #[cfg(debug_assertions)]
            let backend_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("binaries/sm-backend")
                .join(&backend_exe);
            #[cfg(not(debug_assertions))]
            let backend_path = app
                .path()
                .resource_dir()
                .expect("failed to resolve the app's resource directory")
                .join("sm-backend")
                .join(&backend_exe);
            let instance_token = new_instance_token();
            let (mut rx, child) = app
                .shell()
                .command(backend_path)
                .env("SM_INSTANCE_TOKEN", &instance_token)
                .env("SM_EXIT_ON_STDIN_EOF", "1")
                .env("SM_CREDENTIALS_ON_STDIN", "1")
                // Windows text I/O defaults to the ANSI code page, not UTF-8.
                .env("PYTHONUTF8", "1")
                .spawn()
                .expect("failed to spawn sm-backend");
            let backend = Backend {
                child: std::sync::Mutex::new(child),
                instance_token,
            };

            // The backend waits for this line before serving, so read the
            // Keychain after spawning: its startup overlaps any prompt. A
            // credential that can't be read is left out — the backend then
            // reports it missing, as if never stored.
            let stored = CREDENTIAL_KEYS
                .iter()
                .filter_map(|key| match read_credential(key) {
                    Ok(value) => value.map(|v| (key.to_string(), v)),
                    Err(e) => {
                        eprintln!("[credentials] couldn't read '{key}' from the Keychain: {e}");
                        None
                    }
                })
                .collect();
            if let Err(e) = backend.send_credentials(&stored) {
                eprintln!("[credentials] {e}");
            }
            app.manage(backend);

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            let line = String::from_utf8_lossy(&line);
                            match line.strip_prefix(CREDENTIAL_SAVE_PREFIX) {
                                Some(json) => save_credentials_from_backend(json.trim_end()),
                                None => println!("[backend] {line}"),
                            }
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_credential,
            set_credential,
            backend_instance_token
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
