import datetime
import inspect
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional
from migrator.config import (
    ProgressStatus,
    ItemProgressState,
    get_detected_app_groups,
    is_admin
)

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

        for idx, item in enumerate(selected_items):
            current_pct = int(5 + (idx / max(1, total_steps)) * 90)
            update_progress(current_pct, f"Backing up {item.name}...", completed_steps, total_steps)
            set_item_state(item.id, "running", "Backing up...")
            log(f"\n--- [{idx+1}/{total_steps}] Processing: {item.name} ---")

            try:
                from migrator.providers import ProviderRegistry
                provider = ProviderRegistry.get(item.id)
                if provider:
                    success = provider.backup(backup_root, log)
                    if success:
                        set_item_state(item.id, "completed", "Saved")
                    else:
                        set_item_state(item.id, "skipped", "Not found or skipped")
                else:
                    log(f"  [Warning] No provider registered for item: {item.id}")
                    set_item_state(item.id, "skipped", "Provider not found")
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

        for idx, item in enumerate(selected_items):
            current_pct = int(5 + (idx / max(1, total_steps)) * 90)
            update_progress(current_pct, f"Restoring {item.name}...", completed_steps, total_steps)
            set_item_state(item.id, "running", "Restoring...")
            log(f"\n--- [{idx+1}/{total_steps}] Processing: {item.name} ---")

            try:
                from migrator.providers import ProviderRegistry
                provider = ProviderRegistry.get(item.id)
                if provider:
                    success = provider.restore(backup_root, log)
                    if success:
                        set_item_state(item.id, "completed", "Restored")
                    else:
                        set_item_state(item.id, "skipped", "Not in backup or skipped")
                else:
                    log(f"  [Warning] No provider registered for item: {item.id}")
                    set_item_state(item.id, "skipped", "Provider not found")
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

