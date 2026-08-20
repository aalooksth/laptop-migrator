import ctypes
import os
import string
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

def is_admin() -> bool:
    """Check if the current process is running with Administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def get_default_backup_path() -> Path:
    """Determine the default backup path, preferring OneDrive if available."""
    candidates = [
        os.environ.get("OneDrive"),
        os.environ.get("OneDriveConsumer"),
        os.environ.get("OneDriveCommercial"),
        str(Path.home() / "OneDrive"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c) / "LaptopMigrationBackup"
    return Path.home() / "LaptopMigrationBackup"

def list_system_drives() -> List[str]:
    """List available system drives on Windows."""
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives

class SubItemMeta(BaseModel):
    id: str
    name: str
    description: str
    category: str = "Function"
    admin_required_restore: bool = False
    default_enabled: bool = True
    is_detected: bool = True
    detection_info: Optional[str] = None

class AppGroupMeta(BaseModel):
    id: str
    name: str
    icon: str
    software_family: str  # e.g. "System", "Developer", "IDEs & Editors", "Browsers", "Applications"
    is_detected: bool = True
    detection_info: Optional[str] = None
    sub_items: List[SubItemMeta] = Field(default_factory=list)

def get_detected_app_groups() -> List[AppGroupMeta]:
    """Dynamically discover installed software, categories, and sub-components."""
    from migrator.providers import ProviderRegistry, GROUP_METADATA
    
    # Group all registered providers by group_id
    grouped_providers: Dict[str, List[Any]] = {}
    for provider in ProviderRegistry.all().values():
        gid = provider.group_id
        if gid not in grouped_providers:
            grouped_providers[gid] = []
        grouped_providers[gid].append(provider)

    app_groups = []
    # We iterate through GROUP_METADATA to preserve order
    for gid, meta in GROUP_METADATA.items():
        if gid not in grouped_providers:
            continue
        
        providers = grouped_providers[gid]
        sub_items = []
        group_detected = False
        
        for p in providers:
            detected = p.is_detected()
            if detected:
                group_detected = True
                
            sub_items.append(SubItemMeta(
                id=p.id,
                name=p.name,
                description=p.description,
                category=p.category,
                admin_required_restore=p.admin_required_restore,
                default_enabled=p.default_enabled,
                is_detected=detected,
                detection_info=p.detection_info
            ))
            
        app_groups.append(AppGroupMeta(
            id=gid,
            name=meta["name"],
            icon=meta["icon"],
            software_family=meta["software_family"],
            is_detected=group_detected,
            detection_info=meta.get("detection_info", "Detected" if group_detected else "Not Installed"),
            sub_items=sub_items
        ))
    return app_groups


class MigrationRequest(BaseModel):
    backup_path: Optional[str] = None
    options: Dict[str, bool] = Field(default_factory=dict)


class SystemInfoResponse(BaseModel):
    is_admin: bool
    default_backup_path: str
    groups: List[AppGroupMeta]


class ItemProgressState(BaseModel):
    id: str
    status: str = "pending"  # "pending", "running", "completed", "skipped", "failed"
    message: str = ""


class ProgressStatus(BaseModel):
    is_running: bool = False
    action: str = "idle"  # "backup", "restore", "idle"
    current_step: str = "Ready"
    percent: int = 0
    total_steps: int = 0
    completed_steps: int = 0
    error: Optional[str] = None
    item_states: Dict[str, ItemProgressState] = Field(default_factory=dict)
    logs: List[str] = Field(default_factory=list)


class BrowseResponse(BaseModel):
    current_path: Optional[str] = None
    parent_path: Optional[str] = None
    folders: List[str] = Field(default_factory=list)
    drives: List[str] = Field(default_factory=list)
    shortcuts: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None


APP_INSTALL_COMMANDS: Dict[str, str] = {
    "group_vscode": "winget install Microsoft.VisualStudioCode --accept-package-agreements",
    "group_notepadpp": "winget install Notepad++.Notepad++ --accept-package-agreements",
    "group_chrome": "winget install Google.Chrome --accept-package-agreements",
    "group_firefox": "winget install Mozilla.Firefox --accept-package-agreements",
    "group_office": "winget install Microsoft.Office --accept-package-agreements",
    "group_antigravity": "Install Google Antigravity IDE from your portal or website",
}


class BackupInspectionResponse(BaseModel):
    is_backup: bool
    path: str
    item_count: int
    found_sub_items: List[str] = Field(default_factory=list)
    found_groups: List[str] = Field(default_factory=list)
    app_install_commands: Dict[str, str] = Field(default_factory=dict)


def inspect_backup_directory(target_path: Path) -> BackupInspectionResponse:
    """Inspects a target directory to determine if it is a valid Laptop Migration Hub backup and lists available components."""
    from migrator.providers import ProviderRegistry
    if not target_path.exists() or not target_path.is_dir():
        return BackupInspectionResponse(
            is_backup=False,
            path=str(target_path),
            item_count=0,
            found_sub_items=[],
            found_groups=[],
            app_install_commands=APP_INSTALL_COMMANDS
        )

    found_items = []
    for provider_id, provider in ProviderRegistry.all().items():
        try:
            if provider.is_in_backup(target_path):
                found_items.append(provider_id)
        except Exception:
            continue

    groups = get_detected_app_groups()
    found_groups = []
    for g in groups:
        if any(item.id in found_items for item in g.sub_items):
            found_groups.append(g.id)

    return BackupInspectionResponse(
        is_backup=len(found_items) > 0,
        path=str(target_path.resolve()),
        item_count=len(found_items),
        found_sub_items=found_items,
        found_groups=found_groups,
        app_install_commands=APP_INSTALL_COMMANDS
    )

