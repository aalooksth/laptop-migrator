from pathlib import Path
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from migrator.config import (
    MigrationRequest,
    SystemInfoResponse,
    ProgressStatus,
    BrowseResponse,
    BackupInspectionResponse,
    get_detected_app_groups,
    get_default_backup_path,
    list_system_drives,
    is_admin,
    inspect_backup_directory,
)
from migrator.worker import (
    STATUS,
    execute_backup,
    execute_restore,
)

app = FastAPI(
    title="Laptop Migration Hub",
    description="Intelligent Windows configuration backup & restore utility",
    version="2.5.0"
)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    ico_path = STATIC_DIR / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path, media_type="image/x-icon")
    return HTMLResponse(status_code=404)

@app.get("/api/info", response_model=SystemInfoResponse)
def get_system_info():
    """Returns system capabilities, admin privilege state, default paths, and grouped config items."""
    return SystemInfoResponse(
        is_admin=is_admin(),
        default_backup_path=str(get_default_backup_path()),
        groups=get_detected_app_groups()
    )

@app.get("/api/backup/inspect", response_model=BackupInspectionResponse)
def inspect_backup(path: Optional[str] = Query(None)):
    """Inspects a target directory to determine if it contains a valid backup archive and lists present items."""
    target_path = Path(path.strip()) if path and path.strip() else get_default_backup_path()
    return inspect_backup_directory(target_path)

@app.get("/api/status", response_model=ProgressStatus)
def get_progress_status():
    """Returns real-time progress status, per-item state, and logs."""
    return STATUS

@app.post("/api/logs/clear")
def clear_logs():
    """Clear in-memory execution logs."""
    STATUS.logs.clear()
    return {"status": "cleared"}

@app.post("/api/status/reset")
def reset_status():
    """Reset active progress status back to idle."""
    if not STATUS.is_running:
        STATUS.percent = 0
        STATUS.current_step = "Ready"
        STATUS.completed_steps = 0
        STATUS.total_steps = 0
        STATUS.action = "idle"
        STATUS.error = None
        STATUS.item_states.clear()
        STATUS.logs.clear()
    return {"status": "reset"}

class MkdirRequest(BaseModel):
    path: str

@app.get("/api/browse", response_model=BrowseResponse)
def browse_directory(path: Optional[str] = Query(None)):
    """Interactive directory browser API for path navigation."""
    shortcuts = {
        "OneDrive": str(get_default_backup_path().parent),
        "User Home": str(Path.home()),
        "Desktop": str(Path.home() / "Desktop"),
        "Documents": str(Path.home() / "Documents"),
    }
    drives = list_system_drives()

    if not path or not path.strip():
        return BrowseResponse(
            drives=drives,
            shortcuts=shortcuts,
            current_path=None,
            parent_path=None,
            folders=[]
        )

    target = Path(path.strip())
    if not target.exists():
        return BrowseResponse(
            current_path=str(target),
            parent_path=str(target.parent) if target.parent != target else None,
            folders=[],
            drives=drives,
            shortcuts=shortcuts,
            error=f"Directory '{target}' does not exist."
        )

    folders = []
    try:
        for entry in target.iterdir():
            try:
                if entry.is_dir() and not entry.name.startswith("$") and not entry.name.startswith("System Volume Information"):
                    folders.append(entry.name)
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError) as e:
        return BrowseResponse(
            current_path=str(target.resolve()),
            parent_path=str(target.parent.resolve()) if target.parent != target else None,
            folders=[],
            drives=drives,
            shortcuts=shortcuts,
            error=f"Access denied: {e}"
        )

    return BrowseResponse(
        current_path=str(target.resolve()),
        parent_path=str(target.parent.resolve()) if target.parent != target else None,
        folders=sorted(folders, key=lambda s: s.lower()),
        drives=drives,
        shortcuts=shortcuts
    )

@app.post("/api/browse/mkdir")
def create_directory(req: MkdirRequest):
    """Create a new folder."""
    try:
        p = Path(req.path.strip())
        p.mkdir(parents=True, exist_ok=True)
        return {"status": "created", "path": str(p.resolve())}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/backup")
def start_backup(req: MigrationRequest, bg: BackgroundTasks):
    """Trigger background backup task."""
    if STATUS.is_running:
        raise HTTPException(status_code=409, detail="A migration task is already in progress.")
    
    target_path = Path(req.backup_path.strip()) if req.backup_path and req.backup_path.strip() else get_default_backup_path()
    bg.add_task(execute_backup, target_path, req.options)
    return {"status": "Backup initiated", "target_path": str(target_path)}

@app.post("/api/restore")
def start_restore(req: MigrationRequest, bg: BackgroundTasks):
    """Trigger background restore task."""
    if STATUS.is_running:
        raise HTTPException(status_code=409, detail="A migration task is already in progress.")
    
    target_path = Path(req.backup_path.strip()) if req.backup_path and req.backup_path.strip() else get_default_backup_path()
    bg.add_task(execute_restore, target_path, req.options)
    return {"status": "Restore initiated", "target_path": str(target_path)}

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("favicon.ico")

@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Laptop Migration Hub | Windows Config Backup & Restore</title>
    <meta name="description" content="Seamless Windows developer environment, multi-timezone clocks, wifi profiles, dotfiles, and app data migration tool.">
    <meta name="author" content="Laptop Migration Hub">
    <link rel="icon" type="image/x-icon" href="./favicon.ico">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --font-sans: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', Consolas, monospace;
            
            --bg-primary: #090d16;
            --bg-secondary: #0f172a;
            --bg-card: rgba(30, 41, 59, 0.7);
            --bg-card-hover: rgba(51, 65, 85, 0.8);
            --border-color: rgba(148, 163, 184, 0.15);
            --border-accent: rgba(56, 189, 248, 0.3);
            
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            
            --accent-primary: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.25);
            --accent-backup: #0284c7;
            --accent-backup-hover: #0369a1;
            --accent-restore: #10b981;
            --accent-restore-hover: #059669;
            
            --badge-admin-bg: rgba(239, 68, 68, 0.15);
            --badge-admin-text: #f87171;
            --badge-admin-border: rgba(239, 68, 68, 0.3);
            
            --badge-user-bg: rgba(16, 185, 129, 0.15);
            --badge-user-text: #34d399;
            --badge-user-border: rgba(16, 185, 129, 0.3);

            --badge-detect-bg: rgba(56, 189, 248, 0.12);
            --badge-detect-text: #38bdf8;
            --badge-detect-border: rgba(56, 189, 248, 0.25);

            --badge-category-bg: rgba(139, 92, 246, 0.15);
            --badge-category-text: #c084fc;
            --badge-category-border: rgba(139, 92, 246, 0.3);

            --terminal-bg: #030712;
            --terminal-border: #1f2937;
            --terminal-text: #34d399;
            --terminal-header: #111827;
            
            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 14px;
            --shadow-card: 0 8px 24px -6px rgba(0, 0, 0, 0.4);
            --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        [data-theme="light"] {
            --bg-primary: #f8fafc;
            --bg-secondary: #ffffff;
            --bg-card: rgba(255, 255, 255, 0.95);
            --bg-card-hover: rgba(241, 245, 249, 0.95);
            --border-color: rgba(100, 116, 139, 0.2);
            --border-accent: rgba(2, 132, 199, 0.4);
            
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #64748b;
            
            --accent-primary: #0284c7;
            --accent-glow: rgba(2, 132, 199, 0.15);
            --accent-backup: #0284c7;
            --accent-backup-hover: #0369a1;
            --accent-restore: #059669;
            --accent-restore-hover: #047857;

            --badge-admin-bg: rgba(220, 38, 38, 0.12);
            --badge-admin-text: #b91c1c;
            --badge-admin-border: rgba(220, 38, 38, 0.25);
            
            --badge-user-bg: rgba(5, 150, 105, 0.12);
            --badge-user-text: #047857;
            --badge-user-border: rgba(5, 150, 105, 0.25);

            --badge-detect-bg: rgba(2, 132, 199, 0.1);
            --badge-detect-text: #0284c7;
            --badge-detect-border: rgba(2, 132, 199, 0.2);

            --badge-category-bg: rgba(124, 58, 237, 0.1);
            --badge-category-text: #6d28d9;
            --badge-category-border: rgba(124, 58, 237, 0.2);

            --terminal-bg: #0f172a;
            --terminal-border: #334155;
            --terminal-text: #38bdf8;
            --terminal-header: #1e293b;
            
            --shadow-card: 0 8px 20px -4px rgba(0, 0, 0, 0.08);
        }

        /* Restore Mode Theme Enhancements */
        body.mode-restore {
            --border-accent: rgba(16, 185, 129, 0.4);
            --accent-primary: #10b981;
            --accent-glow: rgba(16, 185, 129, 0.2);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: var(--font-sans);
            background-color: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.4;
            padding-bottom: 70px;
            transition: background-color 0.3s ease, color 0.3s ease;
        }

        .container {
            max-width: 1180px;
            margin: 0 auto;
            padding: 1rem 1rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        /* --- Dynamic Sticky Top Progress Bar --- */
        #topProgressBanner {
            position: sticky;
            top: 0;
            z-index: 1000;
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-accent);
            box-shadow: 0 8px 20px -4px rgba(0,0,0,0.4);
            padding: 0.6rem 1.25rem;
            display: none;
            animation: slideDown 0.3s ease-out;
        }

        @keyframes slideDown {
            from { transform: translateY(-100%); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .top-progress-inner {
            max-width: 1180px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }

        .top-progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.82rem;
            font-weight: 600;
        }

        .top-progress-step {
            color: var(--accent-primary);
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .top-progress-track {
            width: 100%;
            height: 8px;
            background: var(--bg-secondary);
            border-radius: 9999px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }

        .top-progress-bar {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #0284c7, #38bdf8, #10b981);
            background-size: 200% 100%;
            border-radius: 9999px;
            transition: width 0.3s ease;
            animation: shimmer 2s infinite linear;
        }

        .top-progress-bar.error-bar { background: #ef4444 !important; }

        @keyframes shimmer {
            0% { background-position: 100% 0; }
            100% { background-position: -100% 0; }
        }

        /* Header & Navigation */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.75rem;
            padding: 0.85rem 1.25rem;
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            box-shadow: var(--shadow-card);
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .brand-icon {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            border-radius: var(--radius-sm);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
            box-shadow: 0 4px 10px var(--accent-glow);
        }

        body.mode-restore .brand-icon {
            background: linear-gradient(135deg, #059669, #10b981);
        }

        .brand-title h1 {
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(to right, var(--text-primary), var(--accent-primary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .brand-title p { font-size: 0.75rem; color: var(--text-secondary); }

        .header-controls {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            flex-wrap: wrap;
        }

        .privilege-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 0.3rem 0.65rem;
            border-radius: 9999px;
        }

        .privilege-admin { background: var(--badge-admin-bg); color: var(--badge-admin-text); border: 1px solid var(--badge-admin-border); }
        .privilege-user { background: var(--badge-user-bg); color: var(--badge-user-text); border: 1px solid var(--badge-user-border); }

        .theme-switcher {
            display: flex;
            align-items: center;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 9999px;
            padding: 3px;
            gap: 2px;
        }

        .theme-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            cursor: pointer;
            font-size: 0.88rem;
            transition: var(--transition);
            line-height: 1;
        }

        .theme-btn:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.06);
        }

        .theme-btn.active {
            background: var(--accent-primary);
            color: #090d16;
            box-shadow: 0 2px 8px var(--accent-glow);
        }

        /* Creator Header Badge */
        .creator-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(139, 92, 246, 0.15));
            border: 1px solid rgba(56, 189, 248, 0.35);
            padding: 0.35rem 0.8rem;
            border-radius: 9999px;
            font-size: 0.76rem;
            font-weight: 700;
            color: var(--accent-primary);
            text-decoration: none;
            transition: var(--transition);
            box-shadow: 0 2px 8px rgba(56, 189, 248, 0.12);
        }

        .creator-badge:hover {
            transform: translateY(-1px);
            border-color: var(--accent-primary);
            box-shadow: 0 4px 14px var(--accent-glow);
            color: #ffffff;
        }

        .creator-link-arrow {
            font-size: 0.8rem;
            opacity: 0.8;
            transition: transform 0.2s ease;
        }

        .creator-badge:hover .creator-link-arrow {
            transform: translate(2px, -2px);
        }

        /* Top Navigation Tabs */
        .app-nav-tabs {
            display: flex;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 4px;
            gap: 4px;
            box-shadow: var(--shadow-card);
            flex-wrap: wrap;
        }

        .nav-tab-btn {
            flex: 1;
            min-width: 160px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.45rem;
            padding: 0.6rem 1rem;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-weight: 700;
            font-size: 0.84rem;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: var(--transition);
            text-decoration: none;
        }

        .nav-tab-btn:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.04);
        }

        .nav-tab-btn.active {
            background: var(--accent-primary);
            color: #090d16;
            box-shadow: 0 2px 10px var(--accent-glow);
        }

        /* Guide & Capabilities View */
        .guide-view {
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        .guide-hero {
            background: linear-gradient(135deg, rgba(2, 132, 199, 0.15), rgba(16, 185, 129, 0.1));
            border: 1px solid var(--border-accent);
            border-radius: var(--radius-md);
            padding: 1.5rem;
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .guide-hero h2 {
            font-size: 1.4rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }

        .guide-hero p {
            color: var(--text-secondary);
            font-size: 0.88rem;
            max-width: 680px;
            margin: 0 auto 1rem auto;
            line-height: 1.6;
        }

        .guide-steps-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .guide-step-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 1.2rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            position: relative;
            transition: var(--transition);
        }

        .guide-step-card:hover {
            border-color: var(--accent-primary);
            transform: translateY(-2px);
        }

        .guide-step-num {
            width: 28px;
            height: 28px;
            background: var(--accent-primary);
            color: #090d16;
            border-radius: 50%;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.85rem;
            margin-bottom: 0.25rem;
        }

        .guide-step-card h3 {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .guide-step-card p {
            font-size: 0.82rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }

        .matrix-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1rem;
        }

        .matrix-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 1.15rem;
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
        }

        .matrix-card-title {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--accent-primary);
            padding-bottom: 0.35rem;
            border-bottom: 1px solid var(--border-color);
        }

        .matrix-list {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }

        .matrix-list li {
            display: flex;
            align-items: flex-start;
            gap: 0.4rem;
            line-height: 1.45;
        }

        .matrix-list li b {
            color: var(--text-primary);
        }

        /* Author & Contact Box */
        .author-card {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95));
            border: 1px solid var(--border-accent);
            border-radius: var(--radius-md);
            padding: 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 1.25rem;
            box-shadow: var(--shadow-card);
        }

        .author-left {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .author-avatar {
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: linear-gradient(135deg, #0284c7, #38bdf8);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.8rem;
            box-shadow: 0 4px 14px var(--accent-glow);
        }

        .author-info h3 {
            font-size: 1.1rem;
            font-weight: 800;
            color: var(--text-primary);
            margin-bottom: 0.2rem;
        }

        .author-info p {
            font-size: 0.82rem;
            color: var(--text-secondary);
        }

        .author-links {
            display: flex;
            gap: 0.6rem;
            flex-wrap: wrap;
        }

        .author-btn {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.5rem 1rem;
            border-radius: var(--radius-sm);
            font-size: 0.82rem;
            font-weight: 700;
            text-decoration: none;
            transition: var(--transition);
        }

        .author-btn-primary {
            background: var(--accent-primary);
            color: #090d16;
        }

        .author-btn-primary:hover {
            background: #7dd3fc;
            transform: translateY(-1px);
        }

        .author-btn-outline {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
        }

        .author-btn-outline:hover {
            border-color: var(--accent-primary);
            color: var(--accent-primary);
            transform: translateY(-1px);
        }

        /* --- Mode Switcher (Backup vs Restore Mode) --- */
        .mode-segmented-control {
            display: flex;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 4px;
            gap: 4px;
        }

        .mode-tab {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.65rem 1rem;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-weight: 700;
            font-size: 0.86rem;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: var(--transition);
        }

        .mode-tab.active {
            background: var(--bg-card-hover);
            color: var(--text-primary);
            box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        }

        #tabBackupMode.active {
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
        }

        #tabRestoreMode.active {
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        /* Backup Detection Alert Callout */
        .backup-detected-alert {
            background: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: var(--radius-md);
            padding: 0.65rem 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.6rem;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }

        .alert-left {
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .alert-icon { font-size: 1.2rem; }
        .alert-title { font-size: 0.84rem; font-weight: 700; color: #34d399; display: block; }
        .alert-sub { font-size: 0.74rem; color: var(--text-secondary); display: block; }

        .alert-btn {
            background: #10b981;
            color: #090d16;
            border: none;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.35rem 0.85rem;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: var(--transition);
        }

        .alert-btn:hover { background: #34d399; }

        /* Instruction Note Banner */
        .instruction-banner {
            background: linear-gradient(90deg, rgba(56, 189, 248, 0.08), rgba(16, 185, 129, 0.08));
            border: 1px solid var(--border-accent);
            border-radius: var(--radius-md);
            padding: 0.65rem 1rem;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            font-size: 0.8rem;
            color: var(--text-primary);
            line-height: 1.5;
        }

        .instruction-banner a {
            color: var(--accent-primary);
            text-decoration: underline;
            font-weight: 600;
        }

        /* Card System */
        .card {
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 1.15rem;
            box-shadow: var(--shadow-card);
            transition: var(--transition);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.85rem;
            flex-wrap: wrap;
            gap: 0.6rem;
        }

        .card-header h2 {
            font-size: 1.05rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        /* Path Configuration */
        .path-group {
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }

        .path-label {
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .path-input-wrapper {
            display: flex;
            gap: 0.4rem;
            flex-wrap: wrap;
        }

        .path-input {
            flex: 1;
            min-width: 260px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.55rem 0.85rem;
            border-radius: var(--radius-sm);
            font-family: var(--font-mono);
            font-size: 0.82rem;
            outline: none;
            transition: var(--transition);
        }

        .path-input:focus {
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 2px var(--accent-glow);
        }

        .btn-outline {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            padding: 0.55rem 0.85rem;
            border-radius: var(--radius-sm);
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }

        .btn-outline:hover {
            border-color: var(--accent-primary);
            color: var(--accent-primary);
        }

        /* Selection Toolbar */
        .selection-toolbar {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            flex-wrap: wrap;
        }

        .filter-btn {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            padding: 0.3rem 0.65rem;
            border-radius: var(--radius-sm);
            font-size: 0.74rem;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
        }

        .filter-btn:hover {
            color: var(--text-primary);
            border-color: var(--border-accent);
        }

        /* --- 3-Tier Hierarchy: Software Family Categories --- */
        .software-family-section {
            margin-bottom: 1.25rem;
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
        }

        .family-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 0.35rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
        }

        .family-title {
            font-size: 0.88rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--accent-primary);
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .family-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 0.75rem;
        }

        .app-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 0.75rem 0.9rem;
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
            transition: var(--transition);
        }

        .uninstalled-warning-banner {
            background: rgba(239, 68, 68, 0.08);
            border: 1px dashed rgba(239, 68, 68, 0.3);
            border-radius: var(--radius-sm);
            padding: 0.5rem 0.75rem;
            font-size: 0.74rem;
            color: #f87171;
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }

        .cmd-copy-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--bg-primary);
            border: 1px solid rgba(148, 163, 184, 0.15);
            padding: 0.2rem 0.45rem;
            border-radius: 4px;
            font-family: var(--font-mono);
            font-size: 0.68rem;
            color: var(--text-primary);
        }

        .copy-cmd-btn {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.62rem;
            padding: 0.1rem 0.35rem;
            border-radius: 3px;
            cursor: pointer;
        }

        .copy-cmd-btn:hover { color: var(--accent-primary); }

        .uninstalled-bar {
            margin-top: 0.85rem;
            padding: 0.65rem 0.95rem;
            background: rgba(148, 163, 184, 0.04);
            border: 1px dashed var(--border-color);
            border-radius: var(--radius-sm);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 0.5rem;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .uninstalled-bar-title {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            font-weight: 600;
        }

        .uninstalled-chips {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            flex-wrap: wrap;
        }

        .uninstalled-chip {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            padding: 0.15rem 0.5rem;
            border-radius: 9999px;
            font-size: 0.7rem;
            color: var(--text-muted);
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }

        .app-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 0.45rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.1);
        }

        .app-info {
            display: flex;
            align-items: center;
            gap: 0.45rem;
        }

        .app-icon { font-size: 1.1rem; }
        .app-name { font-size: 0.88rem; font-weight: 700; color: var(--text-primary); }

        .app-header-actions {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .app-badge {
            font-size: 0.62rem;
            font-weight: 700;
            padding: 0.12rem 0.45rem;
            border-radius: 9999px;
            text-transform: uppercase;
        }

        .badge-detect { background: var(--badge-detect-bg); color: var(--badge-detect-text); border: 1px solid var(--badge-detect-border); }

        .btn-sub-toggle {
            background: transparent;
            border: none;
            color: var(--accent-primary);
            font-size: 0.7rem;
            font-weight: 600;
            cursor: pointer;
            padding: 0 0.2rem;
        }

        .btn-sub-toggle:hover { text-decoration: underline; }

        /* Compact Sub-Items List */
        .sub-items-list {
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }

        .sub-item-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.35rem 0.5rem;
            border-radius: var(--radius-sm);
            background: rgba(148, 163, 184, 0.03);
            border: 1px solid transparent;
            cursor: pointer;
            transition: var(--transition);
        }

        .sub-item-row:hover {
            background: rgba(56, 189, 248, 0.05);
            border-color: rgba(56, 189, 248, 0.2);
        }

        .sub-item-row.checked {
            border-color: rgba(56, 189, 248, 0.25);
            background: rgba(56, 189, 248, 0.04);
        }

        body.mode-restore .sub-item-row.checked {
            border-color: rgba(16, 185, 129, 0.3);
            background: rgba(16, 185, 129, 0.05);
        }

        .sub-item-left {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            flex: 1;
            min-width: 0;
        }

        .sub-item-checkbox {
            width: 1rem;
            height: 1rem;
            accent-color: var(--accent-primary);
            cursor: pointer;
            flex-shrink: 0;
        }

        .sub-item-title {
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--text-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .sub-item-right {
            display: flex;
            align-items: center;
            gap: 0.3rem;
            flex-shrink: 0;
        }

        .sub-item-badge {
            font-size: 0.6rem;
            font-weight: 700;
            padding: 0.1rem 0.35rem;
            border-radius: 9999px;
        }

        .sub-admin { background: var(--badge-admin-bg); color: var(--badge-admin-text); }
        .sub-user { background: var(--badge-user-bg); color: var(--badge-user-text); }
        .sub-func { background: var(--badge-category-bg); color: var(--badge-category-text); border: 1px solid var(--badge-category-border); font-size: 0.58rem; }

        .sub-status-badge {
            font-size: 0.62rem;
            font-weight: 700;
            padding: 0.1rem 0.4rem;
            border-radius: 9999px;
            display: none;
        }

        .status-running { display: inline-flex; background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
        .status-completed { display: inline-flex; background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .status-skipped { display: inline-flex; background: rgba(148, 163, 184, 0.2); color: #94a3b8; }
        .status-failed { display: inline-flex; background: rgba(239, 68, 68, 0.2); color: #f87171; }

        /* Action Buttons */
        .actions-row {
            display: flex;
            gap: 0.75rem;
            margin-top: 0.5rem;
        }

        .actions-row .btn-action {
            flex: 1;
        }

        .btn-action {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.8rem 1.25rem;
            font-size: 0.92rem;
            font-weight: 700;
            border: none;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: var(--transition);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }

        .btn-backup { background: var(--accent-backup); color: #ffffff; }
        .btn-backup:hover:not(:disabled) { background: var(--accent-backup-hover); transform: translateY(-1px); }

        .btn-restore { background: var(--accent-restore); color: #ffffff; }
        .btn-restore:hover:not(:disabled) { background: var(--accent-restore-hover); transform: translateY(-1px); }

        .btn-action:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }

        /* Results Summary in Modal */
        .results-summary-box {
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-sm);
            max-height: 180px;
            overflow-y: auto;
            padding: 0.4rem;
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }

        .summary-result-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.3rem 0.5rem;
            background: var(--bg-secondary);
            border-radius: 4px;
            font-size: 0.76rem;
        }

        .summary-result-title { font-weight: 600; color: var(--text-primary); }
        .summary-result-msg { font-size: 0.7rem; color: var(--text-muted); }

        /* Footer */
        .app-footer {
            text-align: center;
            font-size: 0.75rem;
            color: var(--text-muted);
            padding: 1rem;
        }

        .app-footer a {
            color: var(--accent-primary);
            text-decoration: underline;
            font-weight: 600;
        }

        /* --- Bottom Pullable Drawer for Logs --- */
        #logDrawer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            z-index: 999;
            background: var(--terminal-bg);
            border-top: 2px solid var(--border-accent);
            box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.5);
            transition: height 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            height: 42px;
            display: flex;
            flex-direction: column;
        }

        #logDrawer.expanded { height: 280px; }
        #logDrawer.maximized { height: 75vh; }

        .drawer-header {
            background: var(--terminal-header);
            padding: 0.5rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
            border-bottom: 1px solid var(--terminal-border);
        }

        .drawer-title {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--text-primary);
            font-family: var(--font-mono);
        }

        .drawer-pulse {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 6px #10b981;
        }

        .drawer-pulse.idle { background: #64748b; box-shadow: none; }
        .drawer-pulse.running { animation: pulse 1.2s infinite; }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.3); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
        }

        .drawer-controls {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .drawer-btn {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.7rem;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            cursor: pointer;
            transition: var(--transition);
        }

        .drawer-btn:hover { color: var(--text-primary); border-color: var(--accent-primary); }

        .drawer-body {
            flex: 1;
            padding: 0.85rem;
            overflow-y: auto;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            color: var(--terminal-text);
            white-space: pre-wrap;
            line-height: 1.5;
        }

        /* --- Modal Overlays --- */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(6px);
            z-index: 2000;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }

        .modal-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-accent);
            border-radius: var(--radius-md);
            width: 100%;
            max-width: 620px;
            max-height: 85vh;
            display: flex;
            flex-direction: column;
            box-shadow: var(--shadow-card);
            overflow: hidden;
        }

        .modal-header {
            padding: 0.85rem 1.15rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-header h3 { font-size: 1rem; font-weight: 700; }

        .modal-body {
            padding: 0.85rem 1.15rem;
            overflow-y: auto;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .browser-shortcuts {
            display: flex;
            gap: 0.35rem;
            flex-wrap: wrap;
        }

        .shortcut-btn {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.25rem 0.6rem;
            border-radius: var(--radius-sm);
            font-size: 0.74rem;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
        }

        .shortcut-btn:hover { border-color: var(--accent-primary); color: var(--accent-primary); }

        .current-nav-path {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            background: var(--bg-primary);
            padding: 0.5rem 0.75rem;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border-color);
            font-family: var(--font-mono);
            font-size: 0.78rem;
            word-break: break-all;
        }

        .folders-list {
            border: 1px solid var(--border-color);
            border-radius: var(--radius-sm);
            max-height: 250px;
            overflow-y: auto;
            background: var(--bg-primary);
        }

        .folder-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0.75rem;
            cursor: pointer;
            font-size: 0.82rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
            transition: var(--transition);
        }

        .folder-row:hover {
            background: var(--accent-glow);
            color: var(--accent-primary);
        }

        .modal-footer {
            padding: 0.75rem 1.15rem;
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: flex-end;
            gap: 0.6rem;
            background: var(--bg-card);
        }

        .spinner {
            display: inline-block;
            width: 10px;
            height: 10px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            border-top-color: #38bdf8;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <!-- Sticky Top Progress Banner -->
    <div id="topProgressBanner">
        <div class="top-progress-inner">
            <div class="top-progress-header">
                <span class="top-progress-step" id="topStepText">
                    <span class="spinner"></span>
                    <span>Processing Migration...</span>
                </span>
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <span id="topPercentText" style="font-family: var(--font-mono); color: var(--accent-primary); font-weight: 700;">0%</span>
                    <button class="drawer-btn" style="padding: 0.1rem 0.4rem; font-size: 0.75rem;" onclick="dismissTopBanner()" title="Dismiss Progress Banner">✕</button>
                </div>
            </div>
            <div class="top-progress-track">
                <div class="top-progress-bar" id="topProgressBar"></div>
            </div>
        </div>
    </div>

    <div class="container">
        <!-- Top Navigation -->
        <header>
            <div class="brand">
                <div class="brand-icon" id="brandIcon">💻</div>
                <div class="brand-title">
                    <h1 id="brandTitle">Laptop Migration Hub</h1>
                    <p id="brandSub">Windows Environment & Configuration Synchronizer</p>
                </div>
            </div>
            <div class="header-controls">
                <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" class="creator-badge" title="Visit Alok Shrestha's Website">
                    <span>👨‍💻 Created by Alok Shrestha</span>
                    <span class="creator-link-arrow">↗</span>
                </a>
                <div id="privilegeIndicator" class="privilege-badge privilege-user">
                    <span>Checking Privileges...</span>
                </div>
                <div class="theme-switcher" role="group" aria-label="Theme Switcher">
                    <button class="theme-btn" id="theme-light" onclick="setTheme('light')" title="Light Theme">☀️</button>
                    <button class="theme-btn" id="theme-system" onclick="setTheme('system')" title="System Theme (Follows Windows)">💻</button>
                    <button class="theme-btn" id="theme-dark" onclick="setTheme('dark')" title="Dark Theme">🌑</button>
                </div>
            </div>
        </header>

        <!-- Top Navigation Tabs Bar -->
        <nav class="app-nav-tabs" role="navigation" aria-label="Primary Navigation">
            <button class="nav-tab-btn active" id="navTabDashboard" onclick="switchNavTab('dashboard')">
                <span>⚙️</span>
                <span>Migration Dashboard</span>
            </button>
            <button class="nav-tab-btn" id="navTabGuide" onclick="switchNavTab('guide')">
                <span>📖</span>
                <span>How It Works & Capabilities</span>
            </button>
            <button class="nav-tab-btn" id="navTabFeedback" onclick="switchNavTab('feedback')">
                <span>💬</span>
                <span>Feature Request / Bug Report</span>
            </button>
        </nav>

        <!-- VIEW 1: Migration Dashboard -->
        <div id="dashboardView" class="page-view">
            <!-- Mode Segmented Control Switcher -->
            <div class="mode-segmented-control" style="margin-top: 0.85rem;">
                <button class="mode-tab active" id="tabBackupMode" onclick="setMode('backup')">
                    <span>⬆️</span>
                    <span>Backup Mode (Export this Machine)</span>
                </button>
                <button class="mode-tab" id="tabRestoreMode" onclick="setMode('restore')" style="display: none;">
                    <span>⬇️</span>
                    <span>Restore Mode (Import from Backup)</span>
                </button>
            </div>

            <!-- Intelligent Backup Detection Alert Bar -->
            <div id="backupDetectionAlert" class="backup-detected-alert" style="display: none; margin-top: 0.75rem;">
                <div class="alert-left">
                    <span class="alert-icon">📦</span>
                    <div>
                        <span class="alert-title">Existing Backup Archive Detected</span>
                        <span class="alert-sub" id="backupDetectionText">Contains exported modules ready to restore.</span>
                    </div>
                </div>
                <button class="alert-btn" id="btnSwitchToRestore" onclick="setMode('restore')">Switch to Restore Mode ➔</button>
            </div>

            <!-- User Guidance Note with Support Contact -->
            <div class="instruction-banner" style="margin-top: 0.75rem;">
                <span>💡</span>
                <span id="instructionBannerText"><b>Migration Note:</b> The selected components will be backed up to the selected folder. Please manually check and backup your personal files in <b>Downloads</b>, <b>Documents</b>, <b>Desktop</b>, or project folders.</span>
            </div>

            <!-- Main Configuration Card -->
            <main class="card" style="margin-top: 0.85rem;">
                <!-- Backup & Restore Path Configuration with Interactive Browser -->
                <div class="path-group">
                    <div class="path-label">
                        <span id="pathLabelTitle">📁 Migration Directory Location</span>
                        <span style="font-size: 0.72rem; color: var(--text-muted);">OneDrive or Local Storage</span>
                    </div>
                    <div class="path-input-wrapper">
                        <input type="text" id="backupPathInput" class="path-input" placeholder="e.g. D:\\OneDrive\\LaptopMigrationBackup" onchange="inspectCurrentPath()">
                        <button class="btn-outline" onclick="openFolderBrowser()">📁 Browse Folders</button>
                        <button class="btn-outline" onclick="resetDefaultPath()">🔄 Reset Path</button>
                    </div>
                </div>

                <hr style="border: 0; border-top: 1px solid var(--border-color); margin: 0.85rem 0;">

                <!-- Selection Controls Toolbar -->
                <div class="card-header">
                    <h2 id="modulesSectionTitle">⚙️ Categorized Migration Modules & Sub-Components</h2>
                    <div class="selection-toolbar">
                        <button class="filter-btn" onclick="selectAll(true)">Select All</button>
                        <button class="filter-btn" onclick="selectAll(false)">Deselect All</button>
                        <button class="filter-btn" id="btnNonAdmin" onclick="selectNonAdminOnly()">🛡️ Non-Admin Only</button>
                        <button class="filter-btn" onclick="resetAllToDefaults()" style="border-color: rgba(56, 189, 248, 0.4); color: var(--accent-primary);">🔄 Reset All</button>
                    </div>
                </div>

                <!-- 3-Tier Categorized Applications Grid -->
                <div id="groupsContainer">
                    <p style="color: var(--text-muted); font-size: 0.85rem;">Loading configuration registry...</p>
                </div>

                <!-- Migration Actions -->
                <div class="actions-row">
                    <button class="btn-action btn-backup" id="btnBackup" onclick="triggerMigration('backup')">
                        <span>⬆️</span>
                        <span>Start Backup (Export to Target)</span>
                    </button>
                    <button class="btn-action btn-restore" id="btnRestore" onclick="triggerMigration('restore')" style="display: none;">
                        <span>⬇️</span>
                        <span>Start Restore (Import from Target)</span>
                    </button>
                </div>
            </main>
        </div>

        <!-- VIEW 2: How It Works & Capabilities Guide -->
        <div id="guideView" class="page-view guide-view" style="display: none; margin-top: 0.85rem;">
            <div class="guide-hero">
                <h2>🚀 Migrate Your Entire Windows Environment in Minutes</h2>
                <p>Laptop Migration Hub eliminates the tedious manual setup when moving to a new laptop. Automatically preserve unsaved buffers, custom ribbons, multi-timezones, browser data, and developer configs with zero friction.</p>
                <div style="display: flex; justify-content: center; gap: 0.75rem; flex-wrap: wrap;">
                    <button class="author-btn author-btn-primary" onclick="switchNavTab('dashboard')">Launch Migration Tool ➔</button>
                    <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" class="author-btn author-btn-outline">Visit Creator Website 🌐</a>
                </div>
            </div>

            <!-- 3-Step Visual Workflow -->
            <div class="guide-steps-grid">
                <div class="guide-step-card">
                    <div class="guide-step-num">1</div>
                    <h3>Select & Export</h3>
                    <p>Choose the exact applications, unsaved tabs, settings, and Wi-Fi networks to capture. Click <b>Start Backup</b> to export everything into your OneDrive or USB directory.</p>
                </div>
                <div class="guide-step-card">
                    <div class="guide-step-num">2</div>
                    <h3>Zero Vendor Lock-in</h3>
                    <p>All backups are stored as transparent JSON, XML, and directory archives with high-precision file logs (<code>migration.log</code>). 100% offline and secure.</p>
                </div>
                <div class="guide-step-card">
                    <div class="guide-step-num">3</div>
                    <h3>Smart Restore</h3>
                    <p>Open the app on your new machine and select the backup folder. It automatically hides unbacked items and generates 1-click Winget install commands for uninstalled apps.</p>
                </div>
            </div>

            <!-- Full Capability Matrix -->
            <h3 style="font-size: 1.15rem; font-weight: 800; color: var(--text-primary); margin-top: 0.5rem;">⚙️ Supported Software & Deep Capabilities</h3>
            <div class="matrix-grid">
                <div class="matrix-card">
                    <div class="matrix-card-title"><span>💻</span><span>IDEs & Code Editors</span></div>
                    <ul class="matrix-list">
                        <li><span>🔹</span><span><b>Google Antigravity AI</b>: Unsaved scratch tabs, layout (<code>state.vscdb</code>), skills, rules, brain conversations, & cache.</span></li>
                        <li><span>🔹</span><span><b>Visual Studio Code</b>: Unsaved buffers, Activity Bar/themes, <code>settings.json</code>, keybindings, & extension sync.</span></li>
                        <li><span>🔹</span><span><b>Notepad++</b>: Periodic unsaved document backups, active session tabs, <code>config.xml</code>, & custom shortcuts.</span></li>
                    </ul>
                </div>

                <div class="matrix-card">
                    <div class="matrix-card-title"><span>📊</span><span>Office & Productivity</span></div>
                    <ul class="matrix-list">
                        <li><span>🔹</span><span><b>Microsoft Office (Excel/Word/PPT)</b>: Custom Ribbon tabs & Quick Access Toolbar buttons (<code>*.officeUI</code>, <code>*.qat</code>).</span></li>
                        <li><span>🔹</span><span><b>Templates & Macros</b>: Word <code>Normal.dotm</code>, Excel startup workbooks (<code>XLSTART/PERSONAL.XLSB</code>), & startup add-ins.</span></li>
                        <li><span>🔹</span><span><b>Proofing & Signatures</b>: Custom user dictionaries (<code>CUSTOM.DIC</code> in UProof) & Outlook signatures.</span></li>
                    </ul>
                </div>

                <div class="matrix-card">
                    <div class="matrix-card-title"><span>🌐</span><span>Multi-Profile Web Browsers</span></div>
                    <ul class="matrix-list">
                        <li><span>🔹</span><span><b>Google Chrome</b>: Bookmarks, reading lists, local extension configs, & user preferences across all profiles.</span></li>
                        <li><span>🔹</span><span><b>Microsoft Edge</b>: Favorites, extension states, & preferences across multi-profile setups.</span></li>
                        <li><span>🔹</span><span><b>Mozilla Firefox</b>: Places database (<code>places.sqlite</code>, <code>favicons.sqlite</code>), preferences (<code>prefs.js</code>), & extensions.</span></li>
                    </ul>
                </div>

                <div class="matrix-card">
                    <div class="matrix-card-title"><span>🌐</span><span>System, Shell & Network</span></div>
                    <ul class="matrix-list">
                        <li><span>🔹</span><span><b>Windows Multi-Timezones</b>: Additional clocks (e.g. AEST, CST) & international formatting registry settings.</span></li>
                        <li><span>🔹</span><span><b>Wi-Fi Network Profiles</b>: Saved wireless network passwords & netsh connection profiles.</span></li>
                        <li><span>🔹</span><span><b>Winget Manifest</b>: Automated export of all installed Windows software for 1-click batch reinstallation.</span></li>
                        <li><span>🔹</span><span><b>Developer Dotfiles</b>: SSH keys (<code>~/.ssh</code>), Git global configs (<code>~/.gitconfig</code>), shell & Cloud CLI profiles.</span></li>
                    </ul>
                </div>
            </div>

            <!-- Author & Promotion Spotlight Card -->
            <div class="author-card" style="margin-top: 0.5rem;">
                <div class="author-left">
                    <div class="author-avatar">👨‍💻</div>
                    <div class="author-info">
                        <h3>Crafted by Alok Shrestha</h3>
                        <p>Open-source developer building high-impact productivity tools, automation workflows, and developer utilities.</p>
                    </div>
                </div>
                <div class="author-links">
                    <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" class="author-btn author-btn-primary">Visit aloks.com.np 🌐</a>
                    <a href="mailto:hello@aloks.com.np" class="author-btn author-btn-outline">Contact Alok ✉️</a>
                </div>
            </div>
        </div>

        <!-- VIEW 3: Feature Request & Bug Report View -->
        <div id="feedbackView" class="page-view" style="display: none; margin-top: 0.85rem;">
            <div class="card" style="display: flex; flex-direction: column; gap: 1.25rem;">
                <div class="card-header" style="margin-bottom: 0;">
                    <h2>💬 Feedback, Feature Requests & Bug Reporting</h2>
                </div>
                <p style="color: var(--text-secondary); font-size: 0.88rem; line-height: 1.6;">
                    Laptop Migration Hub is continuously evolving. If you have an application or configuration you would like supported, or if you encountered any issue during a migration, we are here to help!
                </p>

                <div class="matrix-grid">
                    <div class="matrix-card">
                        <div class="matrix-card-title"><span>🐛</span><span>Reporting a Bug or Issue</span></div>
                        <p style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;">
                            When reporting a bug, please include your <code>migration.log</code> file from your backup directory. It contains exact millisecond timestamps and source code references that make diagnosing issues instant.
                        </p>
                        <a href="mailto:hello@aloks.com.np?subject=Laptop%20Migration%20Hub%20Bug%20Report&body=Description%20of%20issue:%0A%0AWindows%20Version:%0AItem(s)%20affected:%0A(Please%20attach%20migration.log%20if%20available)" class="author-btn author-btn-outline" style="align-self: flex-start;">Send Bug Report Email ➔</a>
                    </div>

                    <div class="matrix-card">
                        <div class="matrix-card-title"><span>✨</span><span>Requesting New Software Support</span></div>
                        <p style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;">
                            Want us to add support for another IDE (e.g. JetBrains, Sublime), database tool (DBeaver, DataGrip), or specific Windows app? Let us know which software and configuration paths you use!
                        </p>
                        <a href="mailto:hello@aloks.com.np?subject=Laptop%20Migration%20Hub%20Feature%20Request&body=App%20to%20support:%0AConfig%20details:%0A" class="author-btn author-btn-primary" style="align-self: flex-start;">Request Feature ➔</a>
                    </div>
                </div>

                <div class="author-card">
                    <div class="author-left">
                        <div class="author-avatar">✉️</div>
                        <div class="author-info">
                            <h3>Direct Contact</h3>
                            <p>Email: <a href="mailto:hello@aloks.com.np" style="color: var(--accent-primary); font-weight: 600;">hello@aloks.com.np</a> &bull; Portfolio: <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary); font-weight: 600;">aloks.com.np</a></p>
                        </div>
                    </div>
                    <div class="author-links">
                        <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" class="author-btn author-btn-primary">Explore Portfolio 🌐</a>
                    </div>
                </div>
            </div>
        </div>

        <footer class="app-footer" style="margin-top: 1rem;">
            <div style="margin-bottom: 0.35rem; font-weight: 600;">
                💻 Laptop Migration Hub &bull; Crafted with ❤️ by <strong>Alok Shrestha</strong>
            </div>
            <div style="display: flex; justify-content: center; align-items: center; gap: 0.85rem; flex-wrap: wrap; font-size: 0.76rem;">
                <a href="https://aloks.com.np" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary); text-decoration: none; font-weight: 600;">🌐 aloks.com.np</a>
                <span>&bull;</span>
                <a href="mailto:hello@aloks.com.np" style="color: var(--accent-primary); text-decoration: none; font-weight: 600;">✉️ hello@aloks.com.np</a>
            </div>
        </footer>
    </div>

    <!-- Pullable Bottom Console Drawer -->
    <div id="logDrawer">
        <div class="drawer-header" onclick="toggleDrawer()">
            <div class="drawer-title">
                <div class="drawer-pulse idle" id="drawerPulse"></div>
                <span>📟 Execution Console Logs</span>
                <span id="drawerLogCount" style="font-size: 0.72rem; color: var(--text-muted); font-weight: normal;">(0 lines)</span>
            </div>
            <div class="drawer-controls" onclick="event.stopPropagation();">
                <button class="drawer-btn" onclick="copyLogs()">Copy</button>
                <button class="drawer-btn" onclick="clearLogs()">Clear</button>
                <button class="drawer-btn" id="btnToggleDrawer" onclick="toggleDrawer()">▲ Expand</button>
                <button class="drawer-btn" onclick="toggleMaximizeDrawer()">⛶</button>
            </div>
        </div>
        <div class="drawer-body" id="logViewer">Waiting for migration task to initiate...</div>
    </div>

    <!-- Interactive Folder Browser Modal -->
    <div class="modal-overlay" id="folderBrowserModal">
        <div class="modal-card">
            <div class="modal-header">
                <h3>📁 Select Migration Destination Folder</h3>
                <button class="drawer-btn" onclick="closeFolderBrowser()">✕</button>
            </div>
            <div class="modal-body">
                <div class="browser-shortcuts" id="browserShortcuts"></div>
                <div class="current-nav-path">
                    <span style="color: var(--accent-primary);">Path:</span>
                    <span id="browserCurrentPath">...</span>
                </div>
                <div class="folders-list" id="browserFoldersList">
                    <div style="padding: 0.75rem; color: var(--text-muted);">Loading directories...</div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-outline" onclick="closeFolderBrowser()">Cancel</button>
                <button class="btn-action btn-backup" style="padding: 0.45rem 1.1rem; font-size: 0.82rem;" onclick="selectBrowserPath()">Select This Folder</button>
            </div>
        </div>
    </div>

    <!-- Backup Completion Detailed Modal -->
    <div class="modal-overlay" id="backupCompleteModal">
        <div class="modal-card" style="max-width: 580px;">
            <div class="modal-header" style="background: rgba(16, 185, 129, 0.1); border-bottom-color: rgba(16, 185, 129, 0.3);">
                <h3 style="color: #34d399; display: flex; align-items: center; gap: 0.5rem;">
                    <span>🎉</span>
                    <span>Backup Completed Successfully!</span>
                </h3>
                <button class="drawer-btn" onclick="closeBackupCompleteModal()">✕</button>
            </div>
            <div class="modal-body" style="gap: 0.85rem; padding: 1.15rem;">
                <p style="font-size: 0.84rem; line-height: 1.5; color: var(--text-primary);">
                    Selected configuration settings, developer dotfiles, browser data, and AI brains have been successfully exported:
                </p>

                <!-- Dynamic Itemized Summary List -->
                <div class="results-summary-box" id="backupResultsSummary">
                    <div style="font-size: 0.72rem; color: var(--text-muted);">Exported components will appear here.</div>
                </div>

                <!-- Personal File Manual Warning -->
                <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: var(--radius-sm); padding: 0.75rem; font-size: 0.8rem; line-height: 1.45;">
                    <div style="font-weight: 700; color: #f87171; margin-bottom: 0.25rem; display: flex; align-items: center; gap: 0.35rem;">
                        <span>⚠️</span>
                        <span>Manual Files Checklist:</span>
                    </div>
                    <span>Please manually check and copy your personal files in <b>Downloads</b>, <b>Documents</b>, <b>Desktop</b>, or project folders if they are outside OneDrive.</span>
                </div>

                <!-- How to Restore on New Machine -->
                <div style="background: rgba(56, 189, 248, 0.08); border: 1px solid var(--border-accent); border-radius: var(--radius-sm); padding: 0.75rem; font-size: 0.8rem; line-height: 1.5;">
                    <div style="font-weight: 700; color: var(--accent-primary); margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.35rem;">
                        <span>🚀</span>
                        <span>How to Restore on your New Laptop:</span>
                    </div>
                    <ol style="padding-left: 1.2rem; margin: 0; color: var(--text-secondary);">
                        <li><b>Install applications first</b> (or run <code>winget import -i Applications/winget-packages.json</code> from this backup).</li>
                        <li><b>Open Laptop Migration Hub</b> on the new machine.</li>
                        <li><b>Switch to Restore Mode</b> and select this backup folder.</li>
                        <li><b>Selectively check</b> the components you want to restore, and click <b>Start Restore</b>.</li>
                    </ol>
                </div>

                <div style="font-size: 0.76rem; color: var(--text-muted); line-height: 1.4;">
                    For assistance, questions, or issues, contact <strong>Alok</strong>: <a href="mailto:hello@aloks.com.np" style="color: var(--accent-primary); text-decoration: underline; font-weight: 600;">hello@aloks.com.np</a>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: flex-end;">
                <button class="btn-action btn-backup" style="padding: 0.5rem 1.4rem; font-size: 0.85rem;" onclick="closeBackupCompleteModal()">Got It!</button>
            </div>
        </div>
    </div>

    <!-- Restore Completion Detailed Modal -->
    <div class="modal-overlay" id="restoreCompleteModal">
        <div class="modal-card" style="max-width: 580px;">
            <div class="modal-header" style="background: rgba(16, 185, 129, 0.1); border-bottom-color: rgba(16, 185, 129, 0.3);">
                <h3 style="color: #34d399; display: flex; align-items: center; gap: 0.5rem;">
                    <span>🎉</span>
                    <span>Restore Completed Successfully!</span>
                </h3>
                <button class="drawer-btn" onclick="closeRestoreCompleteModal()">✕</button>
            </div>
            <div class="modal-body" style="gap: 0.85rem; padding: 1.15rem;">
                <p style="font-size: 0.84rem; line-height: 1.5; color: var(--text-primary);">
                    Selected configuration settings, developer dotfiles, browser data, and AI brains have been successfully restored to this computer:
                </p>

                <!-- Dynamic Itemized Summary List -->
                <div class="results-summary-box" id="restoreResultsSummary">
                    <div style="font-size: 0.72rem; color: var(--text-muted);">Restored components will appear here.</div>
                </div>

                <div style="background: rgba(56, 189, 248, 0.08); border: 1px solid var(--border-accent); border-radius: var(--radius-sm); padding: 0.75rem; font-size: 0.8rem; line-height: 1.5;">
                    <div style="font-weight: 700; color: var(--accent-primary); margin-bottom: 0.35rem; display: flex; align-items: center; gap: 0.35rem;">
                        <span>💡</span>
                        <span>Recommended Next Steps:</span>
                    </div>
                    <ul style="padding-left: 1.2rem; margin-top: 0.25rem; font-size: 0.78rem; line-height: 1.5;">
                        <li>Restart any open browsers (Chrome/Edge/Firefox) or IDEs (Antigravity/VS Code/Notepad++) to apply restored preferences.</li>
                        <li>Verify your personal documents and project folders.</li>
                    </ul>
                </div>
                <div style="font-size: 0.76rem; color: var(--text-muted); line-height: 1.4;">
                    For assistance, questions, or issues, contact <strong>Alok</strong>: <a href="mailto:hello@aloks.com.np" style="color: var(--accent-primary); text-decoration: underline; font-weight: 600;">hello@aloks.com.np</a>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: flex-end;">
                <button class="btn-action btn-restore" style="padding: 0.5rem 1.4rem; font-size: 0.85rem;" onclick="closeRestoreCompleteModal()">Got It!</button>
            </div>
        </div>
    </div>

    <!-- Application Logic & State Management -->
    <script>
        let SYSTEM_INFO = null;
        let pollerInterval = null;
        let currentBrowserNavPath = '';
        let currentRunningAction = null;
        let currentAppMode = 'backup'; // 'backup' or 'restore'
        let LAST_INSPECTED_BACKUP = null;
        let hasActiveSessionTask = false;
        let hasShownCompletionModal = false;

        function closeBackupCompleteModal() {
            document.getElementById('backupCompleteModal').style.display = 'none';
        }

        function closeRestoreCompleteModal() {
            document.getElementById('restoreCompleteModal').style.display = 'none';
        }

        function dismissTopBanner() {
            hasActiveSessionTask = false;
            document.getElementById('topProgressBanner').style.display = 'none';
        }

        // --- Theme Switcher Logic ---
        function applyTheme(theme) {
            document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
            const btn = document.getElementById(`theme-${theme}`);
            if (btn) btn.classList.add('active');

            let effectiveTheme = theme;
            if (theme === 'system') {
                effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }
            document.documentElement.setAttribute('data-theme', effectiveTheme);
            localStorage.setItem('migrator_theme', theme);
        }

        function setTheme(theme) { applyTheme(theme); }

        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            const savedTheme = localStorage.getItem('migrator_theme') || 'system';
            if (savedTheme === 'system') applyTheme('system');
        });

        // --- Mode Switcher (Backup vs Restore Mode) ---
        function setMode(mode) {
            currentAppMode = mode;
            const tabBackup = document.getElementById('tabBackupMode');
            const tabRestore = document.getElementById('tabRestoreMode');
            const pathTitle = document.getElementById('pathLabelTitle');
            const modulesTitle = document.getElementById('modulesSectionTitle');
            const bannerText = document.getElementById('instructionBannerText');
            const brandIcon = document.getElementById('brandIcon');
            const brandTitle = document.getElementById('brandTitle');
            const btnBackup = document.getElementById('btnBackup');
            const btnRestore = document.getElementById('btnRestore');

            if (mode === 'restore') {
                document.body.classList.add('mode-restore');
                tabBackup.classList.remove('active');
                tabRestore.classList.add('active');
                brandIcon.innerText = '📦';
                brandTitle.innerText = 'Laptop Migration Hub (Restore Mode)';
                pathTitle.innerText = '📁 Source Backup Archive Location (To Import From)';
                modulesTitle.innerText = '📥 Backed Up Modules Found in Archive';
                bannerText.innerHTML = '<b>Restore Mode Active:</b> Selectively check only the components you wish to import to this laptop, then click <b>Start Restore</b> below.';
                btnBackup.style.display = 'none';
                btnRestore.style.display = 'flex';
                document.getElementById('backupDetectionAlert').style.display = 'none';
            } else {
                document.body.classList.remove('mode-restore');
                tabRestore.classList.remove('active');
                tabBackup.classList.add('active');
                brandIcon.innerText = '💻';
                brandTitle.innerText = 'Laptop Migration Hub';
                pathTitle.innerText = '📁 Migration Directory Location';
                modulesTitle.innerText = '⚙️ Categorized Migration Modules & Sub-Components';
                bannerText.innerHTML = '<b>Migration Note:</b> The selected components will be backed up to the selected folder. Please manually check and backup your personal files in <b>Downloads</b>, <b>Documents</b>, <b>Desktop</b>, or project folders.';
                btnBackup.style.display = 'flex';
                btnRestore.style.display = 'none';
                if (LAST_INSPECTED_BACKUP && LAST_INSPECTED_BACKUP.is_backup) {
                    document.getElementById('backupDetectionAlert').style.display = 'flex';
                }
            }

            if (SYSTEM_INFO && SYSTEM_INFO.groups) {
                renderAppGroups(SYSTEM_INFO.groups);
                restoreFormState();
            }
        }

        // --- Inspect Backup Directory ---
        async function inspectCurrentPath() {
            const pathVal = document.getElementById('backupPathInput').value.trim();
            const alertBox = document.getElementById('backupDetectionAlert');
            const alertText = document.getElementById('backupDetectionText');
            const tabRestore = document.getElementById('tabRestoreMode');

            if (!pathVal) {
                alertBox.style.display = 'none';
                if (tabRestore) tabRestore.style.display = 'none';
                LAST_INSPECTED_BACKUP = null;
                if (currentAppMode === 'restore') setMode('backup');
                return;
            }

            try {
                const res = await fetch(`./api/backup/inspect?path=${encodeURIComponent(pathVal)}`);
                const data = await res.json();
                LAST_INSPECTED_BACKUP = data;

                if (data.is_backup) {
                    if (currentAppMode === 'backup') {
                        alertBox.style.display = 'flex';
                        alertText.innerText = `Contains ${data.item_count} backed up component(s) ready to import to this machine. Backing up same component will overwrite the back up, but not delete other existing data.`;
                    } else {
                        alertBox.style.display = 'none';
                    }
                    if (tabRestore) tabRestore.style.display = 'flex';
                } else {
                    alertBox.style.display = 'none';
                    if (tabRestore) tabRestore.style.display = 'none';
                    if (currentAppMode === 'restore') {
                        setMode('backup');
                    }
                }

                // If in restore mode, re-render to only show backed up items
                if (currentAppMode === 'restore' && SYSTEM_INFO) {
                    renderAppGroups(SYSTEM_INFO.groups);
                }
            } catch (err) {
                console.error('Failed to inspect backup:', err);
                alertBox.style.display = 'none';
                if (tabRestore) tabRestore.style.display = 'none';
            }
        }

        // --- State Persistence (LocalStorage) ---
        function saveFormState() {
            const pathVal = document.getElementById('backupPathInput').value;
            const options = {};
            if (SYSTEM_INFO && SYSTEM_INFO.groups) {
                SYSTEM_INFO.groups.forEach(g => {
                    g.sub_items.forEach(item => {
                        const el = document.getElementById(`chk_${item.id}`);
                        if (el) options[item.id] = el.checked;
                    });
                });
            }
            localStorage.setItem('migrator_path', pathVal);
            localStorage.setItem('migrator_options', JSON.stringify(options));
        }

        function restoreFormState() {
            const savedPath = localStorage.getItem('migrator_path');
            if (savedPath && document.getElementById('backupPathInput')) {
                document.getElementById('backupPathInput').value = savedPath;
            }
            
            const savedOptionsStr = localStorage.getItem('migrator_options');
            if (savedOptionsStr) {
                try {
                    const savedOptions = JSON.parse(savedOptionsStr);
                    if (SYSTEM_INFO && SYSTEM_INFO.groups) {
                        SYSTEM_INFO.groups.forEach(g => {
                            g.sub_items.forEach(item => {
                                const el = document.getElementById(`chk_${item.id}`);
                                if (el) {
                                    if (item.id in savedOptions) {
                                        el.checked = savedOptions[item.id];
                                    } else {
                                        el.checked = item.default_enabled;
                                    }
                                    updateSubItemStyle(item.id, el.checked);
                                }
                            });
                        });
                    }
                } catch (e) {
                    console.error('Error parsing saved options:', e);
                }
            }
        }

        function resetDefaultPath() {
            if (SYSTEM_INFO && SYSTEM_INFO.default_backup_path) {
                document.getElementById('backupPathInput').value = SYSTEM_INFO.default_backup_path;
                saveFormState();
                inspectCurrentPath();
            }
        }

        function resetAllToDefaults() {
            if (!confirm('Reset all selections and folder path back to defaults?')) return;
            localStorage.removeItem('migrator_path');
            localStorage.removeItem('migrator_options');
            
            if (SYSTEM_INFO) {
                document.getElementById('backupPathInput').value = SYSTEM_INFO.default_backup_path;
                SYSTEM_INFO.groups.forEach(g => {
                    g.sub_items.forEach(item => {
                        const el = document.getElementById(`chk_${item.id}`);
                        if (el) {
                            el.checked = item.default_enabled;
                            updateSubItemStyle(item.id, el.checked);
                        }
                        const badge = document.getElementById(`status_badge_${item.id}`);
                        if (badge) {
                            badge.className = 'sub-status-badge';
                            badge.innerHTML = '';
                        }
                    });
                });
            }
            hasActiveSessionTask = false;
            currentRunningAction = null;
            hasShownCompletionModal = false;
            document.getElementById('topProgressBanner').style.display = 'none';
            clearLogs();
            fetch('./api/status/reset', { method: 'POST' }).catch(() => {});
            inspectCurrentPath();
        }

        // --- Render 3-Tier Categorized Hierarchy ---
        function renderAppGroups(groups) {
            let displayedGroups = groups;
            const isRestoreMode = (currentAppMode === 'restore');

            // In Restore Mode: Filter out any software/items NOT present in the backup folder!
            if (isRestoreMode && LAST_INSPECTED_BACKUP && LAST_INSPECTED_BACKUP.is_backup) {
                const foundSub = new Set(LAST_INSPECTED_BACKUP.found_sub_items || []);
                displayedGroups = groups.map(g => {
                    const matchedItems = g.sub_items.filter(item => foundSub.has(item.id));
                    if (matchedItems.length === 0) return null;
                    return {
                        ...g,
                        sub_items: matchedItems
                    };
                }).filter(Boolean);
            } else if (!isRestoreMode) {
                // In Backup Mode: only render detected apps in the main cards
                displayedGroups = groups.filter(g => g.is_detected);
            }

            const uninstalledGroups = (!isRestoreMode) ? groups.filter(g => !g.is_detected) : [];

            // Group by software family
            const families = {};
            displayedGroups.forEach(g => {
                const fam = g.software_family || 'Applications';
                if (!families[fam]) families[fam] = [];
                families[fam].push(g);
            });

            let html = '';
            if (isRestoreMode && displayedGroups.length === 0) {
                html = `
                <div style="padding: 1.5rem; text-align: center; background: rgba(148, 163, 184, 0.05); border: 1px dashed var(--border-color); border-radius: var(--radius-md);">
                    <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">📂</div>
                    <div style="font-weight: 700; font-size: 0.95rem; margin-bottom: 0.25rem;">No Backed Up Components Found in Selected Directory</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted);">Please point the directory above to your valid Laptop Migration Hub backup folder.</div>
                </div>
                `;
            } else {
                for (const [familyName, familyGroups] of Object.entries(families)) {
                    html += `
                    <div class="software-family-section">
                        <div class="family-header">
                            <span class="family-title">${familyName}</span>
                            <span style="font-size: 0.7rem; color: var(--text-muted); font-weight: 600;">${familyGroups.length} module(s)</span>
                        </div>
                        <div class="family-grid">
                    `;

                    familyGroups.forEach(g => {
                        const isNotInstalledLocally = !g.is_detected;
                        const installCmd = LAST_INSPECTED_BACKUP && LAST_INSPECTED_BACKUP.app_install_commands ? LAST_INSPECTED_BACKUP.app_install_commands[g.id] : null;

                        html += `
                        <div class="app-card" id="app_group_${g.id}">
                            <div class="app-card-header">
                                <div class="app-info">
                                    <span class="app-icon">${g.icon}</span>
                                    <span class="app-name">${g.name}</span>
                                </div>
                                <div class="app-header-actions">
                                    <span class="app-badge badge-detect">${isRestoreMode ? 'IN BACKUP' : (g.detection_info || 'Installed')}</span>
                                    <button class="btn-sub-toggle" onclick="toggleGroupItems('${g.id}', true)">All</button>
                                    <span style="color: var(--text-muted); font-size: 0.7rem;">|</span>
                                    <button class="btn-sub-toggle" onclick="toggleGroupItems('${g.id}', false)">None</button>
                                </div>
                            </div>
                        `;

                        // If in restore mode and app is NOT installed on this machine, show warning & install helper!
                        if (isRestoreMode && isNotInstalledLocally) {
                            html += `
                            <div class="uninstalled-warning-banner">
                                <span>⚠️ <b>Software Not Installed on this Machine</b>: Install ${g.name} before restoring settings.</span>
                                ${installCmd ? `
                                <div class="cmd-copy-box">
                                    <code>${installCmd}</code>
                                    <button class="copy-cmd-btn" onclick="copyText('${installCmd}')">Copy</button>
                                </div>
                                ` : ''}
                            </div>
                            `;
                        }

                        html += `
                            <div class="sub-items-list" id="sub_list_${g.id}">
                        `;

                        g.sub_items.forEach(item => {
                            const badgeClass = item.admin_required_restore ? 'sub-admin' : 'sub-user';
                            const badgeText = item.admin_required_restore ? 'Admin' : 'User';
                            const isChecked = isRestoreMode ? true : item.default_enabled;

                            html += `
                                <div class="sub-item-row ${isChecked ? 'checked' : ''}" id="row_${item.id}" onclick="toggleSubItem('${item.id}', event)">
                                    <div class="sub-item-left">
                                        <input type="checkbox" id="chk_${item.id}" data-group="${g.id}" class="sub-item-checkbox" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation(); handleSubCheckboxChange('${item.id}');">
                                        <span class="sub-item-title" title="${item.description}">${item.name}</span>
                                    </div>
                                    <div class="sub-item-right">
                                        ${item.category ? `<span class="sub-item-badge sub-func">${item.category}</span>` : ''}
                                        <span class="sub-item-badge ${badgeClass}">${badgeText}</span>
                                        <span class="sub-status-badge" id="status_badge_${item.id}"></span>
                                    </div>
                                </div>
                            `;
                        });

                        html += `
                            </div>
                        </div>
                        `;
                    });

                    html += `
                        </div>
                    </div>
                    `;
                }
            }

            // Render "Other Supported Applications (Not Installed)" bar in backup mode
            if (!isRestoreMode && uninstalledGroups.length > 0) {
                html += `
                <div class="uninstalled-bar">
                    <div class="uninstalled-bar-title">
                        <span>ℹ️</span>
                        <span>Other Supported Applications (Not Installed on this Machine):</span>
                    </div>
                    <div class="uninstalled-chips">
                `;
                uninstalledGroups.forEach(ug => {
                    html += `
                        <span class="uninstalled-chip" title="Supported by migrator but not detected on this computer">
                            <span>${ug.icon}</span>
                            <span>${ug.name}</span>
                        </span>
                    `;
                });
                html += `
                    </div>
                </div>
                `;
            }

            document.getElementById('groupsContainer').innerHTML = html;
        }

        function handleSubCheckboxChange(id) {
            const chk = document.getElementById(`chk_${id}`);
            updateSubItemStyle(id, chk.checked);
            saveFormState();
        }

        function toggleSubItem(id, event) {
            if (event.target.tagName === 'INPUT' || event.target.tagName === 'BUTTON') return;
            const chk = document.getElementById(`chk_${id}`);
            if (chk) {
                chk.checked = !chk.checked;
                updateSubItemStyle(id, chk.checked);
                saveFormState();
            }
        }

        function updateSubItemStyle(id, isChecked) {
            const row = document.getElementById(`row_${id}`);
            if (row) {
                if (isChecked) row.classList.add('checked');
                else row.classList.remove('checked');
            }
        }

        function toggleGroupItems(groupId, check) {
            document.querySelectorAll(`input[data-group="${groupId}"]`).forEach(chk => {
                chk.checked = check;
                const id = chk.id.replace('chk_', '');
                updateSubItemStyle(id, check);
            });
            saveFormState();
        }

        // --- Filter Selections ---
        function selectAll(checked) {
            document.querySelectorAll('.sub-item-checkbox').forEach(chk => {
                chk.checked = checked;
                const id = chk.id.replace('chk_', '');
                updateSubItemStyle(id, checked);
            });
            saveFormState();
        }

        function selectNonAdminOnly() {
            if (!SYSTEM_INFO || !SYSTEM_INFO.groups) return;
            SYSTEM_INFO.groups.forEach(g => {
                g.sub_items.forEach(item => {
                    const el = document.getElementById(`chk_${item.id}`);
                    if (el) {
                        const shouldCheck = !item.admin_required_restore;
                        el.checked = shouldCheck;
                        updateSubItemStyle(item.id, shouldCheck);
                    }
                });
            });
            saveFormState();
        }

        // --- Drawer Controls ---
        function toggleDrawer() {
            const drawer = document.getElementById('logDrawer');
            const btn = document.getElementById('btnToggleDrawer');
            if (drawer.classList.contains('expanded') || drawer.classList.contains('maximized')) {
                drawer.classList.remove('expanded', 'maximized');
                btn.innerText = '▲ Expand';
            } else {
                drawer.classList.add('expanded');
                btn.innerText = '▼ Collapse';
            }
        }

        function toggleMaximizeDrawer() {
            const drawer = document.getElementById('logDrawer');
            if (drawer.classList.contains('maximized')) {
                drawer.classList.remove('maximized');
                drawer.classList.add('expanded');
            } else {
                drawer.classList.add('maximized');
                drawer.classList.remove('expanded');
            }
        }

        function openDrawer() {
            const drawer = document.getElementById('logDrawer');
            const btn = document.getElementById('btnToggleDrawer');
            drawer.classList.add('expanded');
            btn.innerText = '▼ Collapse';
        }

        // --- Folder Browser Modal Logic ---
        async function openFolderBrowser() {
            const modal = document.getElementById('folderBrowserModal');
            modal.style.display = 'flex';
            const currentVal = document.getElementById('backupPathInput').value.trim();
            loadBrowserPath(currentVal || '');
        }

        function closeFolderBrowser() {
            document.getElementById('folderBrowserModal').style.display = 'none';
        }

        async function loadBrowserPath(path) {
            const list = document.getElementById('browserFoldersList');
            const pathDisplay = document.getElementById('browserCurrentPath');
            const shortcutsDiv = document.getElementById('browserShortcuts');
            list.innerHTML = '<div style="padding: 0.75rem; color: var(--text-muted);">Loading folders...</div>';

            try {
                const url = path ? `./api/browse?path=${encodeURIComponent(path)}` : './api/browse';
                const res = await fetch(url);
                const data = await res.json();

                currentBrowserNavPath = data.current_path || '';
                pathDisplay.innerText = currentBrowserNavPath || '(Select a Drive or Shortcut)';

                // Render shortcuts
                shortcutsDiv.innerHTML = '';
                if (data.drives) {
                    data.drives.forEach(d => {
                        const btn = document.createElement('button');
                        btn.className = 'shortcut-btn';
                        btn.innerText = `💾 ${d}`;
                        btn.onclick = () => loadBrowserPath(d);
                        shortcutsDiv.appendChild(btn);
                    });
                }
                if (data.shortcuts) {
                    for (const [sName, sPath] of Object.entries(data.shortcuts)) {
                        const btn = document.createElement('button');
                        btn.className = 'shortcut-btn';
                        btn.innerText = `📁 ${sName}`;
                        btn.onclick = () => loadBrowserPath(sPath);
                        shortcutsDiv.appendChild(btn);
                    }
                }

                // Render subfolders safely using DOM elements
                list.innerHTML = '';
                if (data.parent_path) {
                    const upRow = document.createElement('div');
                    upRow.className = 'folder-row';
                    upRow.innerHTML = '<span>⬆️</span><span style="font-weight: 600;">.. (Up to Parent)</span>';
                    upRow.onclick = () => loadBrowserPath(data.parent_path);
                    list.appendChild(upRow);
                }

                if (data.folders && data.folders.length > 0) {
                    data.folders.forEach(f => {
                        const row = document.createElement('div');
                        row.className = 'folder-row';
                        row.innerHTML = `<span>📁</span><span>${f}</span>`;
                        row.onclick = () => {
                            const newPath = currentBrowserNavPath ? (currentBrowserNavPath.endsWith('\\\\') ? currentBrowserNavPath + f : currentBrowserNavPath + '\\\\' + f) : f;
                            loadBrowserPath(newPath);
                        };
                        list.appendChild(row);
                    });
                } else if (!data.error) {
                    list.innerHTML = '<div style="padding: 0.75rem; color: var(--text-muted);">No subdirectories found</div>';
                }

                if (data.error) {
                    const errDiv = document.createElement('div');
                    errDiv.style.padding = '0.75rem';
                    errDiv.style.color = '#ef4444';
                    errDiv.innerText = data.error;
                    list.appendChild(errDiv);
                }

            } catch (err) {
                list.innerHTML = `<div style="padding: 0.75rem; color: #ef4444;">Browse failed: ${err.message}</div>`;
            }
        }

        function selectBrowserPath() {
            if (currentBrowserNavPath) {
                document.getElementById('backupPathInput').value = currentBrowserNavPath;
                saveFormState();
                inspectCurrentPath();
            }
            closeFolderBrowser();
        }

        // --- API Integration ---
        async function fetchSystemInfo() {
            try {
                const res = await fetch('./api/info');
                SYSTEM_INFO = await res.json();
                
                // Privilege Badge
                const privBadge = document.getElementById('privilegeIndicator');
                if (SYSTEM_INFO.is_admin) {
                    privBadge.className = 'privilege-badge privilege-admin';
                    privBadge.innerHTML = '<span>⚡ Administrator</span>';
                } else {
                    privBadge.className = 'privilege-badge privilege-user';
                    privBadge.innerHTML = '<span>👤 Standard User</span>';
                }

                // Render default path and items
                document.getElementById('backupPathInput').value = SYSTEM_INFO.default_backup_path;
                renderAppGroups(SYSTEM_INFO.groups);
                restoreFormState();
                inspectCurrentPath();

            } catch (err) {
                console.error('Failed to load system info:', err);
                document.getElementById('groupsContainer').innerHTML = `<p style="color: #ef4444;">Failed to load system configuration: ${err.message}</p>`;
            }
        }

        function getOptionsPayload() {
            const options = {};
            if (SYSTEM_INFO && SYSTEM_INFO.groups) {
                SYSTEM_INFO.groups.forEach(g => {
                    g.sub_items.forEach(item => {
                        const el = document.getElementById(`chk_${item.id}`);
                        options[item.id] = el ? el.checked : false;
                    });
                });
            }
            return {
                backup_path: document.getElementById('backupPathInput').value.trim(),
                options: options
            };
        }

        async function triggerMigration(action) {
            const payload = getOptionsPayload();
            const btnBackup = document.getElementById('btnBackup');
            const btnRestore = document.getElementById('btnRestore');
            
            btnBackup.disabled = true;
            btnRestore.disabled = true;

            try {
                const res = await fetch(`./api/${action}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!res.ok) {
                    const data = await res.json();
                    alert(`Error: ${data.detail || 'Failed to start migration'}`);
                    btnBackup.disabled = false;
                    btnRestore.disabled = false;
                    return;
                }

                currentRunningAction = action;
                hasActiveSessionTask = true;
                hasShownCompletionModal = false;
                
                document.getElementById('topProgressBanner').style.display = 'block';
                document.getElementById('topStepText').innerHTML = `<span class="spinner"></span> <span>Initiating ${action}...</span>`;
                document.getElementById('topProgressBar').style.width = '5%';
                document.getElementById('topProgressBar').classList.remove('error-bar');
                document.getElementById('topPercentText').innerText = '5%';
                
                openDrawer();
                startStatusPolling();
            } catch (err) {
                alert(`Request error: ${err.message}`);
                btnBackup.disabled = false;
                btnRestore.disabled = false;
            }
        }

        function startStatusPolling() {
            if (pollerInterval) clearInterval(pollerInterval);
            pollStatus();
            pollerInterval = setInterval(pollStatus, 800);
        }

        function renderCompletedSummary(targetElemId, itemStates) {
            const container = document.getElementById(targetElemId);
            if (!container) return;

            let html = '';
            let count = 0;
            if (itemStates && Object.keys(itemStates).length > 0) {
                // Map item ID to its human-readable title
                const nameMap = {};
                if (SYSTEM_INFO && SYSTEM_INFO.groups) {
                    SYSTEM_INFO.groups.forEach(g => {
                        g.sub_items.forEach(it => { nameMap[it.id] = `${g.icon} ${it.name}`; });
                    });
                }

                for (const [id, state] of Object.entries(itemStates)) {
                    count++;
                    const icon = state.status === 'completed' ? '✅' : (state.status === 'skipped' ? '⚠️' : '❌');
                    const title = nameMap[id] || id;
                    html += `
                    <div class="summary-result-row">
                        <div>
                            <span class="summary-result-title">${icon} ${title}</span>
                            <div class="summary-result-msg">${state.message || state.status}</div>
                        </div>
                        <span class="sub-item-badge ${state.status === 'completed' ? 'sub-user' : 'sub-admin'}">${state.status}</span>
                    </div>
                    `;
                }
            }

            if (count === 0) {
                html = '<div style="padding: 0.5rem; color: var(--text-muted); font-size: 0.76rem;">Task completed successfully.</div>';
            }

            container.innerHTML = html;
        }

        async function pollStatus() {
            try {
                const res = await fetch('./api/status');
                const data = await res.json();
                
                const topBanner = document.getElementById('topProgressBanner');
                const topBar = document.getElementById('topProgressBar');
                const topPct = document.getElementById('topPercentText');
                const topStep = document.getElementById('topStepText');
                const logViewer = document.getElementById('logViewer');
                const drawerPulse = document.getElementById('drawerPulse');
                const drawerCount = document.getElementById('drawerLogCount');
                const btnBackup = document.getElementById('btnBackup');
                const btnRestore = document.getElementById('btnRestore');

                // Keep banner visible while running or upon task completion in active session
                if (data.is_running || hasActiveSessionTask) {
                    topBanner.style.display = 'block';
                    drawerPulse.className = data.is_running ? 'drawer-pulse running' : 'drawer-pulse';
                } else {
                    topBanner.style.display = 'none';
                    drawerPulse.className = 'drawer-pulse idle';
                }

                // Check for completion transitions and render itemized report
                if (!data.is_running && data.percent === 100 && !data.error && !hasShownCompletionModal) {
                    if (currentRunningAction === 'backup') {
                        hasShownCompletionModal = true;
                        currentRunningAction = null;
                        renderCompletedSummary('backupResultsSummary', data.item_states);
                        document.getElementById('backupCompleteModal').style.display = 'flex';
                        inspectCurrentPath();
                    } else if (currentRunningAction === 'restore') {
                        hasShownCompletionModal = true;
                        currentRunningAction = null;
                        renderCompletedSummary('restoreResultsSummary', data.item_states);
                        document.getElementById('restoreCompleteModal').style.display = 'flex';
                    }
                }

                topBar.style.width = `${data.percent}%`;
                topPct.innerText = `${data.percent}%`;
                topStep.innerHTML = data.is_running ? `<span class="spinner"></span> <span>${data.current_step}</span>` : `<span>${data.current_step}</span>`;

                if (data.error) {
                    topBar.classList.add('error-bar');
                    topStep.classList.add('error');
                } else {
                    topBar.classList.remove('error-bar');
                    topStep.classList.remove('error');
                }

                // Update Per-Item Status Badges
                if (data.item_states) {
                    for (const [id, state] of Object.entries(data.item_states)) {
                        const badge = document.getElementById(`status_badge_${id}`);
                        if (badge) {
                            badge.className = `sub-status-badge status-${state.status}`;
                            if (state.status === 'running') badge.innerHTML = '<span class="spinner" style="width:7px; height:7px;"></span> Active';
                            else if (state.status === 'completed') badge.innerHTML = '✅ Done';
                            else if (state.status === 'skipped') badge.innerHTML = '⚠️ Skipped';
                            else if (state.status === 'failed') badge.innerHTML = '❌ Failed';
                            else badge.innerHTML = '';
                        }
                    }
                }

                if (data.logs && data.logs.length > 0) {
                    logViewer.innerText = data.logs.join('\\n');
                    logViewer.scrollTop = logViewer.scrollHeight;
                    drawerCount.innerText = `(${data.logs.length} lines)`;
                }

                if (!data.is_running) {
                    btnBackup.disabled = false;
                    btnRestore.disabled = false;
                } else {
                    btnBackup.disabled = true;
                    btnRestore.disabled = true;
                }

            } catch (err) {
                console.error('Status poll error:', err);
            }
        }

        function copyLogs() {
            const logs = document.getElementById('logViewer').innerText;
            navigator.clipboard.writeText(logs).then(() => {
                alert('Logs copied to clipboard!');
            });
        }

        function copyText(text) {
            navigator.clipboard.writeText(text).then(() => {
                alert('Installation command copied to clipboard!');
            });
        }

        async function clearLogs() {
            document.getElementById('logViewer').innerText = 'Ready...';
            document.getElementById('drawerLogCount').innerText = '(0 lines)';
            try {
                await fetch('./api/logs/clear', { method: 'POST' });
            } catch (e) {
                console.error('Failed to clear logs on server:', e);
            }
        }

        // --- Primary Navigation Tab Switching & State Persistence ---
        function switchNavTab(tabName) {
            const tabs = ['dashboard', 'guide', 'feedback'];
            tabs.forEach(t => {
                const btn = document.getElementById(`navTab${t.charAt(0).toUpperCase() + t.slice(1)}`);
                const view = document.getElementById(`${t}View`);
                if (btn) {
                    if (t === tabName) btn.classList.add('active');
                    else btn.classList.remove('active');
                }
                if (view) {
                    view.style.display = (t === tabName) ? (t === 'guide' ? 'flex' : 'block') : 'none';
                }
            });

            localStorage.setItem('migrator_nav_tab', tabName);
            try {
                history.replaceState(null, null, `#${tabName}`);
            } catch (e) {}
        }

        // --- Initialization ---
        document.addEventListener('DOMContentLoaded', () => {
            const initialTheme = localStorage.getItem('migrator_theme') || 'system';
            applyTheme(initialTheme);
            fetchSystemInfo();
            startStatusPolling();

            // Restore active navigation tab from URL hash or localStorage
            const urlHash = window.location.hash.replace('#', '');
            const savedNavTab = urlHash || localStorage.getItem('migrator_nav_tab') || 'dashboard';
            if (['dashboard', 'guide', 'feedback'].includes(savedNavTab)) {
                switchNavTab(savedNavTab);
            }

            document.getElementById('backupPathInput').addEventListener('input', () => {
                saveFormState();
                inspectCurrentPath();
            });
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    import argparse
    import sys
    import threading
    import webbrowser
    import time

    is_frozen = getattr(sys, 'frozen', False)

    parser = argparse.ArgumentParser(description="Laptop Migration Hub")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port number to listen on (default: 8000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with hot reloading and verbose logs")
    parser.add_argument("--no-browser", action="store_true", help="Disable automatic browser opening on launch")
    args = parser.parse_args()

    app_url = f"http://{args.host}:{args.port}/"

    print(f"\n========================================================================")
    print(f"  💻 Laptop Migration Hub")
    print(f"  Crafted by: Alok Shrestha")
    print(f"  Website:    https://aloks.com.np")
    print(f"  Support:    hello@aloks.com.np")
    print(f"------------------------------------------------------------------------")
    print(f"  --> Local Web UI: {app_url}")
    print(f"  --> Localhost:    http://localhost:{args.port}/")
    print(f"========================================================================\n")

    # Automatically open browser window on startup
    if not args.no_browser and not args.debug:
        def launch_browser():
            time.sleep(1.2)
            webbrowser.open(app_url)
        threading.Thread(target=launch_browser, daemon=True).start()

    should_reload = args.debug and not is_frozen

    uvicorn.run(
        "app:app" if should_reload else app,
        host=args.host,
        port=args.port,
        reload=should_reload,
        log_level="debug" if args.debug else "info"
    )