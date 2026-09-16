// Credential storage (implementation-plan.md Step 2): both Rust and Python
// read/write the same macOS Keychain item directly via this service name —
// no handoff between them, confirmed by a real cross-process test (an item
// created by one process was read cleanly by a different one, no prompt).
// Rust owns the onboarding UI's read/write; Python reads the same item
// independently later when it needs the credential for a real API call.
const CREDENTIAL_SERVICE: &str = "com.ssb.app";

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Step 1 sidecar PoC: spawn the Python backend when the app starts,
            // started/stopped with the app (overview.md §1). Stdout/stderr are
            // logged, not wired to the frontend yet — that's real endpoint work,
            // not part of proving the sidecar mechanism itself.
            let (mut rx, _child) = app
                .shell()
                .sidecar("ssb-backend")
                .expect("failed to create sidecar command")
                .spawn()
                .expect("failed to spawn ssb-backend sidecar");

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
        .invoke_handler(tauri::generate_handler![get_credential, set_credential])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
