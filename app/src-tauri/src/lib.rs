// Credential storage (implementation-plan.md Step 2): both Rust and Python
// read/write the same macOS Keychain item directly via this service name —
// no handoff between them, confirmed by a real cross-process test (an item
// created by one process was read cleanly by a different one, no prompt).
// Rust owns the onboarding UI's read/write; Python reads the same item
// independently later when it needs the credential for a real API call.
const CREDENTIAL_SERVICE: &str = "com.secondmind.app";

#[tauri::command]
fn get_credential(key: String) -> Result<Option<String>, String> {
    use keyring::v1::Entry;
    let entry = Entry::new(CREDENTIAL_SERVICE, &key).map_err(|e| e.to_string())?;
    match entry.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::v1::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn set_credential(key: String, value: String) -> Result<(), String> {
    use keyring::v1::Entry;
    let entry = Entry::new(CREDENTIAL_SERVICE, &key).map_err(|e| e.to_string())?;
    entry.set_password(&value).map_err(|e| e.to_string())
}

// Held for the app's whole lifetime. Dropping the CommandChild closes the
// write end of the backend's stdin, which the backend treats as "the app
// is gone" and exits (main.py's _exit_when_app_closes) — so the child
// must live in managed state, not a local that dies at the end of setup.
// The OS closes that same pipe when this process ends for any reason
// (quit, crash, force quit), which is what stops the backend outliving
// the app and holding port 8756 for the next launch.
struct Backend {
    _child: tauri_plugin_shell::process::CommandChild,
    instance_token: String,
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
                // Windows text I/O defaults to the ANSI code page, not UTF-8.
                .env("PYTHONUTF8", "1")
                .spawn()
                .expect("failed to spawn sm-backend");
            app.manage(Backend {
                _child: child,
                instance_token,
            });

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line));
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
