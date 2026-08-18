import datetime
import inspect
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional
from migrator.config import (
    ProgressStatus,
    ItemProgressState,
    get_detected_app_groups,
    get_antigravity_roaming_path,
    get_antigravity_local_path,
    is_admin
)
from migrator.registry_ops import backup_clock_and_regional, restore_clock_and_regional

# Global progress status tracker & active log file pointer
STATUS = ProgressStatus()
LOG_FILE_PATH: Optional[Path] = None

def log(msg: str, level: str = "INFO"):
    """Log a message with a timestamp, caller file, and line number to memory, console, and backup log file."""
    now = datetime.datetime.now()
    ts_short = now.strftime("%H:%M:%S")
    ts_full = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # Caller frame detection (file and line)
    caller_file = "worker.py"
    caller_line = 0
    try:
        stack = inspect.stack()
        if len(stack) > 1:
            frame = stack[1]
            caller_file = Path(frame.filename).name
            caller_line = frame.lineno
    except Exception:
        pass

    loc_tag = f"[{caller_file}:{caller_line}]" if caller_line else ""
    formatted_console = f"[{ts_short}] {loc_tag} {msg}".strip() if loc_tag else f"[{ts_short}] {msg}"
    STATUS.logs.append(formatted_console)
    print(formatted_console)

    if LOG_FILE_PATH:
        try:
            LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{ts_full}] {loc_tag:<24} [{level:<5}] {msg}\n")
        except Exception as file_err:
            print(f"[Warning] Failed writing to log file: {file_err}")

def update_progress(percent: int, step: str, completed: int, total: int):
    """Update active progress state."""
    STATUS.percent = min(100, max(0, percent))
    STATUS.current_step = step
    STATUS.completed_steps = completed
    STATUS.total_steps = total

def set_item_state(item_id: str, status: str, message: str = ""):
    """Update progress status for an individual configuration item."""
    STATUS.item_states[item_id] = ItemProgressState(id=item_id, status=status, message=message)

def robust_copy_file(src: Path, dest: Path) -> bool:
    """Copy a file safely by stripping read-only attributes, unlinking target, and catching locks."""
    try:
        if not src.exists() or not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            try:
                os.chmod(dest, stat.S_IWRITE)
            except Exception:
                pass
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
        shutil.copy2(src, dest)
        return True
    except Exception as e:
        log(f"  [Notice] Skipped {src.name}: {e}")
        return False

def robust_copytree(src: Path, dest: Path, ignore_patterns: Optional[List[str]] = None):
    """Recursively copy directory handling permission flags, locked files, and sockets."""
    if not src.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    
    for root, dirs, files in os.walk(src):
        rel_path = Path(root).relative_to(src)
        target_dir = dest / rel_path
        target_dir.mkdir(parents=True, exist_ok=True)
        
        for f in files:
            # Skip transient / lock files
            if f.endswith(('.tmp', '.lock', '.sock', '.pid', '.ldb.lock')):
                continue
            s_file = Path(root) / f
            d_file = target_dir / f
            robust_copy_file(s_file, d_file)

def get_all_sub_items():
    groups = get_detected_app_groups()
    items = []
    for g in groups:
        items.extend(g.sub_items)
    return items

def execute_backup(backup_root: Path, options: Dict[str, bool]):
    """Execute the full backup pipeline based on user options."""
    global STATUS, LOG_FILE_PATH
    STATUS.is_running = True
    STATUS.action = "backup"
    STATUS.error = None
    STATUS.logs.clear()
    STATUS.item_states.clear()

    LOG_FILE_PATH = backup_root / "migration.log"
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*85}\n")
            f.write(f"=== MIGRATION BACKUP SESSION: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"=== Host: {os.environ.get('COMPUTERNAME', 'Local')} | User: {os.environ.get('USERNAME', 'User')} | Admin: {is_admin()} ===\n")
            f.write(f"=== Target Path: {backup_root} ===\n")
            f.write(f"{'='*85}\n")
    except Exception as init_err:
        print(f"[Warning] Could not initialize log file: {init_err}")
    
    all_items = get_all_sub_items()
    selected_items = [item for item in all_items if options.get(item.id, item.default_enabled)]
    total_steps = len(selected_items)
    completed_steps = 0

    for item in selected_items:
        set_item_state(item.id, "pending", "Waiting in queue")

    log(f"=== Starting Migration Backup ===")
    log(f"Destination: {backup_root}")
    log(f"Admin Privileges: {'Active (Elevated)' if is_admin() else 'Standard User (Non-Elevated)'}")
    log(f"Selected Components ({total_steps}): {', '.join([i.name for i in selected_items])}")

    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        update_progress(5, "Initializing backup environment...", 0, total_steps)

        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        userhome = Path.home()
        ag_roaming = get_antigravity_roaming_path()
        ag_local = get_antigravity_local_path()

        for idx, item in enumerate(selected_items):
            current_pct = int(5 + (idx / max(1, total_steps)) * 90)
            update_progress(current_pct, f"Backing up {item.name}...", completed_steps, total_steps)
            set_item_state(item.id, "running", "Backing up...")
            log(f"\n--- [{idx+1}/{total_steps}] Processing: {item.name} ---")

            try:
                # 1. System Clock
                if item.id == "system_clock":
                    backup_clock_and_regional(backup_root, log)
                    set_item_state(item.id, "completed", "Exported")

                # 2. Wi-Fi Profiles
                elif item.id == "system_wifi":
                    wifi_dest = backup_root / "System" / "WiFi"
                    wifi_dest.mkdir(parents=True, exist_ok=True)
                    log("Exporting Wi-Fi profiles via netsh...")
                    res = subprocess.run(
                        f'netsh wlan export profile folder="{wifi_dest}" key=clear',
                        shell=True,
                        capture_output=True,
                        text=True
                    )
                    xml_count = len(list(wifi_dest.glob("*.xml")))
                    log(f"  -> Exported {xml_count} Wi-Fi profile(s).")
                    set_item_state(item.id, "completed", f"{xml_count} profiles")

                # 3. SSH Keys
                elif item.id == "dotfiles_ssh":
                    src = userhome / ".ssh"
                    if src.exists():
                        dest = backup_root / "Dotfiles" / ".ssh"
                        robust_copytree(src, dest)
                        log(f"  -> Backed up .ssh keys and config.")
                        set_item_state(item.id, "completed", "SSH keys saved")
                    else:
                        set_item_state(item.id, "skipped", "Directory not found")

                # 4. Git Config
                elif item.id == "dotfiles_git":
                    dest = backup_root / "Dotfiles"
                    dest.mkdir(parents=True, exist_ok=True)
                    for g in [".gitconfig", ".gitignore_global"]:
                        src = userhome / g
                        if src.exists():
                            robust_copy_file(src, dest / g)
                            log(f"  -> Backed up {g}")
                    set_item_state(item.id, "completed", "Git configs saved")

                # 5. Shell Profiles
                elif item.id == "dotfiles_shell":
                    dest = backup_root / "Dotfiles"
                    dest.mkdir(parents=True, exist_ok=True)
                    for s in [".bash_profile", ".bashrc", ".zshrc", ".config", ".aws", ".kube"]:
                        src = userhome / s
                        if src.exists():
                            if src.is_dir():
                                robust_copytree(src, dest / s)
                            else:
                                robust_copy_file(src, dest / s)
                            log(f"  -> Backed up {s}")
                    set_item_state(item.id, "completed", "Shell configs saved")

                # 6. Antigravity Unsaved Files & Workspace Buffers
                elif item.id == "antigravity_unsaved":
                    dest = backup_root / "Antigravity" / "Roaming_IDE"
                    saved = False
                    if ag_roaming and ag_roaming.exists():
                        backups_dir = ag_roaming / "Backups"
                        if backups_dir.exists():
                            robust_copytree(backups_dir, dest / "Backups")
                            saved = True
                        ws_dir = ag_roaming / "User" / "workspaceStorage"
                        if ws_dir.exists():
                            robust_copytree(ws_dir, dest / "User" / "workspaceStorage")
                            saved = True
                    if saved:
                        log(f"  -> Backed up Antigravity unsaved file backups and workspace storage.")
                        set_item_state(item.id, "completed", "Unsaved buffers saved")
                    else:
                        log("  -> No active Antigravity backup buffers found.")
                        set_item_state(item.id, "skipped", "No buffers found")

                # 7. Antigravity Settings, Theme & UI Layout
                elif item.id == "antigravity_settings":
                    dest = backup_root / "Antigravity" / "Roaming_IDE" / "User"
                    dest.mkdir(parents=True, exist_ok=True)
                    if ag_roaming and (ag_roaming / "User").exists():
                        u_src = ag_roaming / "User"
                        for f in ["settings.json", "keybindings.json"]:
                            if (u_src / f).exists():
                                robust_copy_file(u_src / f, dest / f)
                        for folder in ["snippets", "History", "globalStorage"]:
                            if (u_src / folder).exists():
                                robust_copytree(u_src / folder, dest / folder)
                        log("  -> Backed up Antigravity settings (Activity Bar, Themes), UI layout database (state.vscdb), keybindings, and history.")
                        set_item_state(item.id, "completed", "Settings & Layout saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 8. Antigravity Config & Rules
                elif item.id == "antigravity_config":
                    src = userhome / ".gemini" / "config"
                    if src.exists():
                        dest = backup_root / "Antigravity" / "gemini_config"
                        robust_copytree(src, dest)
                        log(f"  -> Backed up Antigravity config, skills and rules.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 9. Antigravity Brain
                elif item.id == "antigravity_brain":
                    src = userhome / ".gemini" / "antigravity-ide"
                    if src.exists():
                        dest = backup_root / "Antigravity" / "gemini_ide"
                        robust_copytree(src, dest)
                        log(f"  -> Backed up Antigravity conversations & knowledge.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 10. Antigravity Local Cache
                elif item.id == "antigravity_cache":
                    if ag_local and ag_local.exists():
                        dest = backup_root / "Antigravity" / "local_appdata"
                        robust_copytree(ag_local, dest)
                        log(f"  -> Backed up Antigravity local app data.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 11. VS Code Unsaved Buffers
                elif item.id == "vscode_unsaved":
                    src_backups = appdata / "Code" / "Backups"
                    src_storage = appdata / "Code" / "User" / "workspaceStorage"
                    dest = backup_root / "VSCode"
                    found = False
                    if src_backups.exists():
                        robust_copytree(src_backups, dest / "Backups")
                        found = True
                    if src_storage.exists():
                        robust_copytree(src_storage, dest / "User" / "workspaceStorage")
                        found = True
                    if found:
                        log("  -> Backed up VS Code workspace storage and unsaved buffers.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "No buffers found")

                # 12. VS Code Settings, Theme & UI Layout
                elif item.id == "vscode_settings":
                    src = appdata / "Code" / "User"
                    if src.exists():
                        dest = backup_root / "VSCode" / "User"
                        dest.mkdir(parents=True, exist_ok=True)
                        for f in ["settings.json", "keybindings.json"]:
                            if (src / f).exists():
                                robust_copy_file(src / f, dest / f)
                        for folder in ["snippets", "History", "globalStorage"]:
                            if (src / folder).exists():
                                robust_copytree(src / folder, dest / folder)
                        log("  -> Backed up VS Code settings, themes, UI layout (state.vscdb), keybindings, and history.")
                        set_item_state(item.id, "completed", "Settings saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 13. VS Code Extensions Metadata
                elif item.id == "vscode_extensions":
                    src = userhome / ".vscode" / "extensions"
                    if src.exists():
                        dest = backup_root / "VSCode" / "extensions"
                        robust_copytree(src, dest)
                        log("  -> Backed up VS Code extensions.")
                        set_item_state(item.id, "completed", "Extensions saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 14. Notepad++ Unsaved Files & Sessions
                elif item.id == "notepadpp_unsaved":
                    npp_dir = appdata / "Notepad++"
                    dest = backup_root / "Notepad++"
                    found = False
                    if npp_dir.exists():
                        if (npp_dir / "backup").exists():
                            robust_copytree(npp_dir / "backup", dest / "backup")
                            found = True
                        if (npp_dir / "session.xml").exists():
                            robust_copy_file(npp_dir / "session.xml", dest / "session.xml")
                            found = True
                    if found:
                        log("  -> Backed up Notepad++ unsaved document backups and active session tabs.")
                        set_item_state(item.id, "completed", "Unsaved tabs saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 15. Notepad++ Configuration & Plugins
                elif item.id == "notepadpp_config":
                    npp_dir = appdata / "Notepad++"
                    dest = backup_root / "Notepad++"
                    if npp_dir.exists():
                        dest.mkdir(parents=True, exist_ok=True)
                        for f in ["config.xml", "shortcuts.xml", "contextMenu.xml", "userDefineLang.xml", "stylers.xml"]:
                            if (npp_dir / f).exists():
                                robust_copy_file(npp_dir / f, dest / f)
                        if (npp_dir / "plugins").exists():
                            robust_copytree(npp_dir / "plugins", dest / "plugins")
                        log("  -> Backed up Notepad++ configuration, shortcuts, and plugin settings.")
                        set_item_state(item.id, "completed", "Config saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 16. Chrome Bookmarks
                elif item.id == "chrome_bookmarks":
                    chrome_src = localappdata / "Google" / "Chrome" / "User Data"
                    if chrome_src.exists():
                        for prof in chrome_src.iterdir():
                            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                                bm = prof / "Bookmarks"
                                if bm.exists():
                                    robust_copy_file(bm, backup_root / "Chrome" / prof.name / "Bookmarks")
                        log("  -> Backed up Chrome Bookmarks.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 17. Chrome Extensions & Preferences
                elif item.id == "chrome_extensions":
                    chrome_src = localappdata / "Google" / "Chrome" / "User Data"
                    if chrome_src.exists():
                        for prof in chrome_src.iterdir():
                            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                                target = backup_root / "Chrome" / prof.name
                                if (prof / "Preferences").exists():
                                    robust_copy_file(prof / "Preferences", target / "Preferences")
                                for ext in ["Local Extension Settings", "Sync Extension Settings"]:
                                    if (prof / ext).exists():
                                        robust_copytree(prof / ext, target / ext)
                        log("  -> Backed up Chrome Extension data and Preferences.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 18. Edge Bookmarks
                elif item.id == "edge_bookmarks":
                    edge_src = localappdata / "Microsoft" / "Edge" / "User Data"
                    if edge_src.exists():
                        for prof in edge_src.iterdir():
                            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                                bm = prof / "Bookmarks"
                                if bm.exists():
                                    robust_copy_file(bm, backup_root / "Edge" / prof.name / "Bookmarks")
                        log("  -> Backed up Microsoft Edge Bookmarks.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 19. Edge Extensions & Preferences
                elif item.id == "edge_extensions":
                    edge_src = localappdata / "Microsoft" / "Edge" / "User Data"
                    if edge_src.exists():
                        for prof in edge_src.iterdir():
                            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                                target = backup_root / "Edge" / prof.name
                                if (prof / "Preferences").exists():
                                    robust_copy_file(prof / "Preferences", target / "Preferences")
                                for ext in ["Local Extension Settings", "Sync Extension Settings"]:
                                    if (prof / ext).exists():
                                        robust_copytree(prof / ext, target / ext)
                        log("  -> Backed up Edge Extension data and Preferences.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 20. Firefox Bookmarks
                elif item.id == "firefox_bookmarks":
                    found = False
                    ff_dirs = [appdata / "Mozilla" / "Firefox" / "Profiles", localappdata / "Mozilla" / "Firefox" / "Profiles"]
                    for ff_src in ff_dirs:
                        if ff_src.exists():
                            for prof in ff_src.iterdir():
                                if prof.is_dir():
                                    target = backup_root / "Firefox" / prof.name
                                    for f in ["places.sqlite", "favicons.sqlite"]:
                                        if (prof / f).exists():
                                            robust_copy_file(prof / f, target / f)
                                            found = True
                    if found:
                        log("  -> Backed up Firefox Bookmarks & History.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 21. Firefox Profiles & Extensions
                elif item.id == "firefox_profiles":
                    found = False
                    ff_dirs = [appdata / "Mozilla" / "Firefox" / "Profiles", localappdata / "Mozilla" / "Firefox" / "Profiles"]
                    for ff_src in ff_dirs:
                        if ff_src.exists():
                            for prof in ff_src.iterdir():
                                if prof.is_dir():
                                    target = backup_root / "Firefox" / prof.name
                                    for f in ["prefs.js", "extensions.json"]:
                                        if (prof / f).exists():
                                            robust_copy_file(prof / f, target / f)
                                            found = True
                                    for folder in ["extensions", "extension-settings"]:
                                        if (prof / folder).exists():
                                            robust_copytree(prof / folder, target / folder)
                                            found = True
                    if found:
                        log("  -> Backed up Firefox Preferences and Extensions.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

                # 22. Winget Manifest
                elif item.id == "app_manifest":
                    apps_dest = backup_root / "Applications"
                    apps_dest.mkdir(parents=True, exist_ok=True)
                    manifest_file = apps_dest / "winget-packages.json"
                    log("Exporting Winget package manifest...")
                    res = subprocess.run(
                        f'winget export -o "{manifest_file}" --accept-source-agreements',
                        shell=True,
                        capture_output=True,
                        text=True
                    )
                    if manifest_file.exists():
                        log(f"  -> Winget package list exported.")
                        set_item_state(item.id, "completed", "Manifest exported")
                    else:
                        set_item_state(item.id, "skipped", "No packages exported")

                # 23. Office Ribbon & Quick Access Toolbar (QAT)
                elif item.id == "office_ribbon_qat":
                    found = False
                    office_local = localappdata / "Microsoft" / "Office"
                    if office_local.exists():
                        ui_dest = backup_root / "Office" / "UI"
                        for f in office_local.glob("*.officeUI"):
                            robust_copy_file(f, ui_dest / f.name)
                            found = True
                        for f in office_local.glob("*.qat"):
                            robust_copy_file(f, ui_dest / f.name)
                            found = True
                    if found:
                        log("  -> Backed up Office Ribbon and Quick Access Toolbar customizations (*.officeUI).")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "No customization files found")

                # 24. Office Templates & Macros
                elif item.id == "office_templates_macros":
                    found = False
                    tpl_src = appdata / "Microsoft" / "Templates"
                    if tpl_src.exists():
                        robust_copytree(tpl_src, backup_root / "Office" / "Templates")
                        found = True
                    xls_src = appdata / "Microsoft" / "Excel" / "XLSTART"
                    if xls_src.exists():
                        robust_copytree(xls_src, backup_root / "Office" / "Excel_XLSTART")
                        found = True
                    wrd_src = appdata / "Microsoft" / "Word" / "STARTUP"
                    if wrd_src.exists():
                        robust_copytree(wrd_src, backup_root / "Office" / "Word_STARTUP")
                        found = True
                    if found:
                        log("  -> Backed up Office Templates (Normal.dotm) and Personal Macros (XLSTART).")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "No templates found")

                # 25. Office Custom Dictionaries & Signatures
                elif item.id == "office_dictionaries_signatures":
                    found = False
                    uproof_src = appdata / "Microsoft" / "UProof"
                    if uproof_src.exists():
                        robust_copytree(uproof_src, backup_root / "Office" / "UProof")
                        found = True
                    sig_src = appdata / "Microsoft" / "Signatures"
                    if sig_src.exists():
                        robust_copytree(sig_src, backup_root / "Office" / "Signatures")
                        found = True
                    if found:
                        log("  -> Backed up Office Custom Dictionaries (CUSTOM.DIC) and Outlook Signatures.")
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found")

            except Exception as item_err:
                log(f"  [Warning] Error on {item.name}: {item_err}")
                set_item_state(item.id, "failed", str(item_err))

            completed_steps += 1

        update_progress(100, "Backup Completed Successfully!", total_steps, total_steps)
        log("\n=== ALL BACKUP TASKS COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        STATUS.error = str(e)
        log(f"\n[ERROR] Backup failed with exception: {e}")
        update_progress(STATUS.percent, f"Failed: {e}", completed_steps, total_steps)
    finally:
        STATUS.is_running = False

def execute_restore(backup_root: Path, options: Dict[str, bool]):
    """Execute the full restore pipeline based on user options."""
    global STATUS, LOG_FILE_PATH
    STATUS.is_running = True
    STATUS.action = "restore"
    STATUS.error = None
    STATUS.logs.clear()
    STATUS.item_states.clear()

    LOG_FILE_PATH = backup_root / "migration.log"
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*85}\n")
            f.write(f"=== MIGRATION RESTORE SESSION: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"=== Host: {os.environ.get('COMPUTERNAME', 'Local')} | User: {os.environ.get('USERNAME', 'User')} | Admin: {is_admin()} ===\n")
            f.write(f"=== Source Path: {backup_root} ===\n")
            f.write(f"{'='*85}\n")
    except Exception as init_err:
        print(f"[Warning] Could not initialize log file: {init_err}")

    if not backup_root.exists():
        STATUS.error = f"Backup directory '{backup_root}' does not exist."
        log(f"[ERROR] {STATUS.error}", level="ERROR")
        STATUS.is_running = False
        return

    all_items = get_all_sub_items()
    selected_items = [item for item in all_items if options.get(item.id, item.default_enabled)]
    total_steps = len(selected_items)
    completed_steps = 0

    for item in selected_items:
        set_item_state(item.id, "pending", "Waiting in queue")

    log(f"=== Starting Migration Restore ===")
    log(f"Source: {backup_root}")
    log(f"Admin Privileges: {'Active (Elevated)' if is_admin() else 'Standard User (Non-Elevated)'}")
    log(f"Selected Components ({total_steps}): {', '.join([i.name for i in selected_items])}")

    try:
        update_progress(5, "Initializing restore environment...", 0, total_steps)

        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        userhome = Path.home()
        ag_roaming = get_antigravity_roaming_path()
        ag_local = get_antigravity_local_path()

        for idx, item in enumerate(selected_items):
            current_pct = int(5 + (idx / max(1, total_steps)) * 90)
            update_progress(current_pct, f"Restoring {item.name}...", completed_steps, total_steps)
            set_item_state(item.id, "running", "Restoring...")
            log(f"\n--- [{idx+1}/{total_steps}] Processing: {item.name} ---")

            try:
                # 1. System Clock
                if item.id == "system_clock":
                    restore_clock_and_regional(backup_root, log)
                    set_item_state(item.id, "completed", "Restored")

                # 2. Wi-Fi Profiles
                elif item.id == "system_wifi":
                    wifi_dir = backup_root / "System" / "WiFi"
                    if wifi_dir.exists():
                        xml_files = list(wifi_dir.glob("*.xml"))
                        log(f"Importing {len(xml_files)} Wi-Fi profile(s)...")
                        for xml in xml_files:
                            res = subprocess.run(
                                f'netsh wlan add profile filename="{xml}" user=all',
                                shell=True,
                                capture_output=True,
                                text=True
                            )
                            if res.returncode == 0:
                                log(f"  -> Added Wi-Fi profile: {xml.stem}")
                            else:
                                log(f"  -> Adding {xml.stem} returned code {res.returncode}. (May require Admin for user=all)")
                        set_item_state(item.id, "completed", f"{len(xml_files)} profiles imported")
                    else:
                        set_item_state(item.id, "skipped", "No profiles found")

                # 3. SSH Keys
                elif item.id == "dotfiles_ssh":
                    src = backup_root / "Dotfiles" / ".ssh"
                    if src.exists():
                        robust_copytree(src, userhome / ".ssh")
                        log("  -> Restored ~/.ssh keys.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 4. Git Config
                elif item.id == "dotfiles_git":
                    src = backup_root / "Dotfiles"
                    for g in [".gitconfig", ".gitignore_global"]:
                        if (src / g).exists():
                            robust_copy_file(src / g, userhome / g)
                            log(f"  -> Restored {g}")
                    set_item_state(item.id, "completed", "Restored")

                # 5. Shell Profiles
                elif item.id == "dotfiles_shell":
                    src = backup_root / "Dotfiles"
                    for s in [".bash_profile", ".bashrc", ".zshrc", ".config", ".aws", ".kube"]:
                        s_src = src / s
                        if s_src.exists():
                            if s_src.is_dir():
                                robust_copytree(s_src, userhome / s)
                            else:
                                robust_copy_file(s_src, userhome / s)
                            log(f"  -> Restored {s}")
                    set_item_state(item.id, "completed", "Restored")

                # 6. Antigravity Unsaved Files & Workspaces
                elif item.id == "antigravity_unsaved":
                    src = backup_root / "Antigravity" / "Roaming_IDE"
                    if src.exists() and ag_roaming:
                        if (src / "Backups").exists():
                            robust_copytree(src / "Backups", ag_roaming / "Backups")
                        if (src / "User" / "workspaceStorage").exists():
                            robust_copytree(src / "User" / "workspaceStorage", ag_roaming / "User" / "workspaceStorage")
                        log("  -> Restored Antigravity unsaved file backups and workspace storage.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 7. Antigravity Settings & History
                elif item.id == "antigravity_settings":
                    src = backup_root / "Antigravity" / "Roaming_IDE" / "User"
                    if src.exists() and ag_roaming:
                        dest_user = ag_roaming / "User"
                        robust_copytree(src, dest_user)
                        log("  -> Restored Antigravity IDE settings, UI layout (state.vscdb), keybindings, and history.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 8. Antigravity Config
                elif item.id == "antigravity_config":
                    src = backup_root / "Antigravity" / "gemini_config"
                    if src.exists():
                        robust_copytree(src, userhome / ".gemini" / "config")
                        log("  -> Restored Antigravity config & skills.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 9. Antigravity Brain
                elif item.id == "antigravity_brain":
                    src = backup_root / "Antigravity" / "gemini_ide"
                    if src.exists():
                        robust_copytree(src, userhome / ".gemini" / "antigravity-ide")
                        log("  -> Restored Antigravity brain conversations.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 10. Antigravity Local Cache
                elif item.id == "antigravity_cache":
                    src = backup_root / "Antigravity" / "local_appdata"
                    if src.exists() and ag_local:
                        robust_copytree(src, ag_local)
                        log("  -> Restored Antigravity local app data.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 11. VS Code Unsaved Buffers
                elif item.id == "vscode_unsaved":
                    src = backup_root / "VSCode"
                    if (src / "Backups").exists():
                        robust_copytree(src / "Backups", appdata / "Code" / "Backups")
                    if (src / "User" / "workspaceStorage").exists():
                        robust_copytree(src / "User" / "workspaceStorage", appdata / "Code" / "User" / "workspaceStorage")
                    log("  -> Restored VS Code unsaved buffers and workspace storage.")
                    set_item_state(item.id, "completed", "Restored")

                # 12. VS Code Settings, Themes & UI Layout
                elif item.id == "vscode_settings":
                    src = backup_root / "VSCode" / "User"
                    if src.exists():
                        robust_copytree(src, appdata / "Code" / "User")
                        log("  -> Restored VS Code settings, themes, UI layout (state.vscdb), keybindings, and history.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 13. VS Code Extensions
                elif item.id == "vscode_extensions":
                    src = backup_root / "VSCode" / "extensions"
                    if src.exists():
                        robust_copytree(src, userhome / ".vscode" / "extensions")
                        log("  -> Restored VS Code extensions.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 14. Notepad++ Unsaved Files & Sessions
                elif item.id == "notepadpp_unsaved":
                    src = backup_root / "Notepad++"
                    npp_dest = appdata / "Notepad++"
                    if src.exists():
                        if (src / "backup").exists():
                            robust_copytree(src / "backup", npp_dest / "backup")
                        if (src / "session.xml").exists():
                            robust_copy_file(src / "session.xml", npp_dest / "session.xml")
                        log("  -> Restored Notepad++ unsaved file backups and session tabs.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 15. Notepad++ Configuration
                elif item.id == "notepadpp_config":
                    src = backup_root / "Notepad++"
                    npp_dest = appdata / "Notepad++"
                    if src.exists():
                        for f in ["config.xml", "shortcuts.xml", "contextMenu.xml", "userDefineLang.xml", "stylers.xml"]:
                            if (src / f).exists():
                                robust_copy_file(src / f, npp_dest / f)
                        if (src / "plugins").exists():
                            robust_copytree(src / "plugins", npp_dest / "plugins")
                        log("  -> Restored Notepad++ configuration and shortcuts.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 16. Chrome Bookmarks
                elif item.id == "chrome_bookmarks":
                    chrome_src = backup_root / "Chrome"
                    if chrome_src.exists():
                        for prof in chrome_src.iterdir():
                            if (prof / "Bookmarks").exists():
                                dest = localappdata / "Google" / "Chrome" / "User Data" / prof.name / "Bookmarks"
                                robust_copy_file(prof / "Bookmarks", dest)
                        log("  -> Restored Chrome bookmarks.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 17. Chrome Extensions & Preferences
                elif item.id == "chrome_extensions":
                    chrome_src = backup_root / "Chrome"
                    if chrome_src.exists():
                        log("Terminating Chrome before restoring preferences...")
                        subprocess.run("taskkill /F /IM chrome.exe /T", shell=True, capture_output=True)
                        for prof in chrome_src.iterdir():
                            target = localappdata / "Google" / "Chrome" / "User Data" / prof.name
                            if (prof / "Preferences").exists():
                                robust_copy_file(prof / "Preferences", target / "Preferences")
                            for ext in ["Local Extension Settings", "Sync Extension Settings"]:
                                if (prof / ext).exists():
                                    robust_copytree(prof / ext, target / ext)
                        log("  -> Restored Chrome extension data and preferences.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 18. Edge Bookmarks
                elif item.id == "edge_bookmarks":
                    edge_src = backup_root / "Edge"
                    if edge_src.exists():
                        for prof in edge_src.iterdir():
                            if (prof / "Bookmarks").exists():
                                dest = localappdata / "Microsoft" / "Edge" / "User Data" / prof.name / "Bookmarks"
                                robust_copy_file(prof / "Bookmarks", dest)
                        log("  -> Restored Microsoft Edge bookmarks.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 19. Edge Extensions & Preferences
                elif item.id == "edge_extensions":
                    edge_src = backup_root / "Edge"
                    if edge_src.exists():
                        log("Terminating Microsoft Edge before restoring preferences...")
                        subprocess.run("taskkill /F /IM msedge.exe /T", shell=True, capture_output=True)
                        for prof in edge_src.iterdir():
                            target = localappdata / "Microsoft" / "Edge" / "User Data" / prof.name
                            if (prof / "Preferences").exists():
                                robust_copy_file(prof / "Preferences", target / "Preferences")
                            for ext in ["Local Extension Settings", "Sync Extension Settings"]:
                                if (prof / ext).exists():
                                    robust_copytree(prof / ext, target / ext)
                        log("  -> Restored Edge extension data and preferences.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 20. Firefox Bookmarks
                elif item.id == "firefox_bookmarks":
                    ff_src = backup_root / "Firefox"
                    if ff_src.exists():
                        for prof in ff_src.iterdir():
                            target = appdata / "Mozilla" / "Firefox" / "Profiles" / prof.name
                            target.mkdir(parents=True, exist_ok=True)
                            for f in ["places.sqlite", "favicons.sqlite"]:
                                if (prof / f).exists():
                                    robust_copy_file(prof / f, target / f)
                        log("  -> Restored Firefox bookmarks.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 21. Firefox Profiles & Extensions
                elif item.id == "firefox_profiles":
                    ff_src = backup_root / "Firefox"
                    if ff_src.exists():
                        log("Terminating Firefox before restoring preferences...")
                        subprocess.run("taskkill /F /IM firefox.exe /T", shell=True, capture_output=True)
                        for prof in ff_src.iterdir():
                            target = appdata / "Mozilla" / "Firefox" / "Profiles" / prof.name
                            target.mkdir(parents=True, exist_ok=True)
                            for f in ["prefs.js", "extensions.json"]:
                                if (prof / f).exists():
                                    robust_copy_file(prof / f, target / f)
                            for folder in ["extensions", "extension-settings"]:
                                if (prof / folder).exists():
                                    robust_copytree(prof / folder, target / folder)
                        log("  -> Restored Firefox preferences and extensions.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 22. Winget Manifest
                elif item.id == "app_manifest":
                    manifest = backup_root / "Applications" / "winget-packages.json"
                    if manifest.exists():
                        log("Restoring applications via Winget import...")
                        res = subprocess.run(
                            f'winget import -i "{manifest}" --accept-package-agreements --accept-source-agreements',
                            shell=True,
                            capture_output=True,
                            text=True
                        )
                        log(f"  -> Winget import executed with return code {res.returncode}.")
                        set_item_state(item.id, "completed", "Packages imported")
                    else:
                        set_item_state(item.id, "skipped", "No manifest found")

                # 23. Office Ribbon & Quick Access Toolbar (QAT)
                elif item.id == "office_ribbon_qat":
                    ui_src = backup_root / "Office" / "UI"
                    if ui_src.exists():
                        log("Closing Excel, Word, and PowerPoint before restoring UI customizations...")
                        subprocess.run("taskkill /F /IM excel.exe /T", shell=True, capture_output=True)
                        subprocess.run("taskkill /F /IM winword.exe /T", shell=True, capture_output=True)
                        subprocess.run("taskkill /F /IM powerpnt.exe /T", shell=True, capture_output=True)
                        dest = localappdata / "Microsoft" / "Office"
                        dest.mkdir(parents=True, exist_ok=True)
                        for f in ui_src.iterdir():
                            if f.is_file():
                                robust_copy_file(f, dest / f.name)
                        log("  -> Restored Office Ribbon and Quick Access Toolbar customizations (*.officeUI).")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 24. Office Templates & Macros
                elif item.id == "office_templates_macros":
                    found = False
                    tpl_src = backup_root / "Office" / "Templates"
                    if tpl_src.exists():
                        robust_copytree(tpl_src, appdata / "Microsoft" / "Templates")
                        found = True
                    xls_src = backup_root / "Office" / "Excel_XLSTART"
                    if xls_src.exists():
                        robust_copytree(xls_src, appdata / "Microsoft" / "Excel" / "XLSTART")
                        found = True
                    wrd_src = backup_root / "Office" / "Word_STARTUP"
                    if wrd_src.exists():
                        robust_copytree(wrd_src, appdata / "Microsoft" / "Word" / "STARTUP")
                        found = True
                    if found:
                        log("  -> Restored Office Templates (Normal.dotm) and Personal Macros (XLSTART).")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

                # 25. Office Custom Dictionaries & Signatures
                elif item.id == "office_dictionaries_signatures":
                    found = False
                    uproof_src = backup_root / "Office" / "UProof"
                    if uproof_src.exists():
                        robust_copytree(uproof_src, appdata / "Microsoft" / "UProof")
                        found = True
                    sig_src = backup_root / "Office" / "Signatures"
                    if sig_src.exists():
                        robust_copytree(sig_src, appdata / "Microsoft" / "Signatures")
                        found = True
                    if found:
                        log("  -> Restored Office Custom Dictionaries (CUSTOM.DIC) and Outlook Signatures.")
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup")

            except Exception as item_err:
                log(f"  [Warning] Error restoring {item.name}: {item_err}")
                set_item_state(item.id, "failed", str(item_err))

            completed_steps += 1

        update_progress(100, "Restore Completed Successfully!", total_steps, total_steps)
        log("\n=== ALL RESTORE TASKS COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        STATUS.error = str(e)
        log(f"\n[ERROR] Restore failed with exception: {e}")
        update_progress(STATUS.percent, f"Failed: {e}", completed_steps, total_steps)
    finally:
        STATUS.is_running = False
