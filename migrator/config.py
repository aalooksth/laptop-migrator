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

def get_antigravity_roaming_path() -> Optional[Path]:
    """Find the Antigravity IDE roaming directory."""
    appdata = Path(os.environ.get("APPDATA", ""))
    for candidate in ["Antigravity IDE", "Antigravity", "antigravity"]:
        p = appdata / candidate
        if p.exists():
            return p
    return appdata / "Antigravity IDE"

def get_antigravity_local_path() -> Optional[Path]:
    """Find the Antigravity IDE local directory."""
    localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    for candidate in ["antigravity", "Antigravity", "Antigravity IDE"]:
        p = localappdata / candidate
        if p.exists():
            return p
    return localappdata / "antigravity"

def get_detected_app_groups() -> List[AppGroupMeta]:
    """Dynamically discover installed software, categories, and sub-components."""
    appdata = Path(os.environ.get("APPDATA", ""))
    localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    userprofile = Path(os.environ.get("USERPROFILE", ""))

    # 1. Chrome detection
    chrome_path = localappdata / "Google" / "Chrome" / "User Data"
    chrome_detected = chrome_path.exists()
    chrome_profs = []
    if chrome_detected:
        chrome_profs = [p.name for p in chrome_path.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))]
    chrome_info = f"{len(chrome_profs)} profile(s)" if chrome_detected else "Not Installed"

    # 2. Edge detection
    edge_path = localappdata / "Microsoft" / "Edge" / "User Data"
    edge_detected = edge_path.exists()
    edge_profs = []
    if edge_detected:
        edge_profs = [p.name for p in edge_path.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile "))]
    edge_info = f"{len(edge_profs)} profile(s)" if edge_detected else "Not Installed"

    # 3. Firefox detection
    firefox_roaming = appdata / "Mozilla" / "Firefox" / "Profiles"
    firefox_local = localappdata / "Mozilla" / "Firefox" / "Profiles"
    ff_prog = Path("C:/Program Files/Mozilla Firefox/firefox.exe").exists() or Path("C:/Program Files (x86)/Mozilla Firefox/firefox.exe").exists()
    
    firefox_profs = set()
    for base in [firefox_roaming, firefox_local]:
        if base.exists():
            for p in base.iterdir():
                if p.is_dir():
                    firefox_profs.add(p.name)
    
    firefox_detected = bool(firefox_profs) or ff_prog or (appdata / "Mozilla" / "Firefox").exists() or (localappdata / "Mozilla" / "Firefox").exists()
    firefox_info = f"{len(firefox_profs)} profile(s)" if firefox_profs else ("Installed" if firefox_detected else "Not Installed")

    # 4. VS Code detection
    vscode_path = appdata / "Code" / "User"
    vscode_detected = vscode_path.exists() or (userprofile / ".vscode").exists()
    vscode_info = "Installed" if vscode_detected else "Not Installed"

    # 5. Antigravity detection
    ag_roaming = get_antigravity_roaming_path()
    ag_local = get_antigravity_local_path()
    ag_brain = userprofile / ".gemini" / "antigravity-ide"
    ag_config = userprofile / ".gemini" / "config"
    ag_detected = (ag_roaming and ag_roaming.exists()) or ag_brain.exists() or ag_config.exists() or (ag_local and ag_local.exists())
    ag_info = "Detected" if ag_detected else "Not Installed"
    ag_unsaved_detected = bool(ag_roaming and ((ag_roaming / "Backups").exists() or (ag_roaming / "User" / "workspaceStorage").exists()))

    # 6. Notepad++ detection
    npp_path = appdata / "Notepad++"
    npp_detected = npp_path.exists() or (Path("C:/Program Files/Notepad++").exists()) or (Path("C:/Program Files (x86)/Notepad++").exists())
    npp_info = "Installed" if npp_detected else "Not Installed"
    npp_unsaved_detected = bool(npp_path.exists() and ((npp_path / "backup").exists() or (npp_path / "session.xml").exists()))

    # 7. Microsoft Office detection
    office_local = localappdata / "Microsoft" / "Office"
    office_roaming = appdata / "Microsoft" / "Office"
    office_ui_files = list(office_local.glob("*.officeUI")) if office_local.exists() else []
    office_detected = (
        office_local.exists()
        or office_roaming.exists()
        or (appdata / "Microsoft" / "Excel").exists()
        or (appdata / "Microsoft" / "Word").exists()
        or (appdata / "Microsoft" / "Templates").exists()
    )
    office_info = f"{len(office_ui_files)} UI customization(s)" if office_ui_files else ("Installed" if office_detected else "Not Installed")
    office_ui_detected = bool(office_ui_files)
    office_templates_detected = bool(
        (appdata / "Microsoft" / "Templates").exists()
        or (appdata / "Microsoft" / "Excel" / "XLSTART").exists()
        or (appdata / "Microsoft" / "Word" / "STARTUP").exists()
    )
    office_uproof_detected = bool(
        (appdata / "Microsoft" / "UProof").exists()
        or (appdata / "Microsoft" / "Signatures").exists()
    )

    return [
        # ==========================================
        # Software Family: System Info
        # ==========================================
        AppGroupMeta(
            id="group_system",
            name="Windows Settings",
            icon="🌐",
            software_family="System Info",
            is_detected=True,
            detection_info="Windows Registry",
            sub_items=[
                SubItemMeta(
                    id="system_clock",
                    name="Clock & Multi-Timezones",
                    description="Additional clocks (AEST, CST), international formatting, and system timezone.",
                    category="System",
                    admin_required_restore=False,
                    default_enabled=True,
                    is_detected=True,
                    detection_info="Registry"
                ),
                SubItemMeta(
                    id="system_wifi",
                    name="Wi-Fi Network Profiles",
                    description="Saved Wi-Fi profiles & security keys. (Restoring system-wide requires Admin)",
                    category="Networking",
                    admin_required_restore=True,
                    default_enabled=True,
                    is_detected=True,
                    detection_info="netsh WLAN"
                ),
                SubItemMeta(
                    id="app_manifest",
                    name="Winget Application Manifest/List",
                    description="Inventory of installed Windows software for automated batch reinstallation.",
                    category="Package Manager",
                    admin_required_restore=True,
                    default_enabled=True,
                    is_detected=True,
                    detection_info="winget.json"
                )
            ]
        ),

        AppGroupMeta(
            id="group_developer",
            name="Developer Dotfiles",
            icon="🐚",
            software_family="System Info",
            is_detected=True,
            detection_info="User Profile",
            sub_items=[
                SubItemMeta(
                    id="dotfiles_ssh",
                    name="SSH Keys & Known Hosts (~/.ssh)",
                    description="SSH keypairs, known_hosts, and client configs.",
                    category="Security",
                    admin_required_restore=False,
                    default_enabled=True,
                    is_detected=(Path.home() / ".ssh").exists(),
                    detection_info="~/.ssh"
                ),
                SubItemMeta(
                    id="dotfiles_git",
                    name="Git Configuration (~/.gitconfig)",
                    description="Global git user settings, credential helpers, and global ignores.",
                    category="Version Control",
                    admin_required_restore=False,
                    default_enabled=True,
                    is_detected=(Path.home() / ".gitconfig").exists(),
                    detection_info="~/.gitconfig"
                ),
                SubItemMeta(
                    id="dotfiles_shell",
                    name="Shell & Cloud CLI Configs",
                    description="Configs in ~/.config, ~/.bashrc, ~/.zshrc, ~/.aws, ~/.kube.",
                    category="Shell Environment",
                    admin_required_restore=False,
                    default_enabled=True,
                    is_detected=True,
                    detection_info="~/.config"
                )
            ]
        ),

        # ==========================================
        # Software Family: IDEs & Code Editors
        # ==========================================
        AppGroupMeta(
            id="group_antigravity",
            name="Antigravity AI Platform",
            icon="✨",
            software_family="IDEs & Code Editors",
            is_detected=ag_detected,
            detection_info=ag_info,
            sub_items=[
                SubItemMeta(
                    id="antigravity_unsaved",
                    name="Unsaved Files & Workspace Buffers",
                    description="Active unsaved files, untitled scratch tabs, and hot exit backups in AppData/Roaming/Antigravity IDE/Backups.",
                    category="Unsaved Files",
                    admin_required_restore=False,
                    default_enabled=ag_detected,
                    is_detected=ag_unsaved_detected,
                    detection_info="Backups & Sessions"
                ),
                SubItemMeta(
                    id="antigravity_settings",
                    name="Settings, Theme & UI Layout",
                    description="settings.json (Activity Bar position, color themes, fonts), keybindings.json, globalStorage (state.vscdb layout database), and snippets.",
                    category="Configuration",
                    admin_required_restore=False,
                    default_enabled=ag_detected,
                    is_detected=bool(ag_roaming and (ag_roaming / "User").exists()),
                    detection_info="settings.json & state.vscdb"
                ),
                SubItemMeta(
                    id="antigravity_config",
                    name="Rules, Skills & Plugins",
                    description="Global custom skills, behavioral rules, and plugin configs in ~/.gemini/config.",
                    category="Customizations",
                    admin_required_restore=False,
                    default_enabled=ag_detected,
                    is_detected=ag_config.exists(),
                    detection_info="~/.gemini/config"
                ),
                SubItemMeta(
                    id="antigravity_brain",
                    name="Brain (Conversations & Knowledge)",
                    description="Transcripts, knowledge base, artifacts, conversation trajectories, and tool schemas (~/.gemini/antigravity-ide).",
                    category="Conversations",
                    admin_required_restore=False,
                    default_enabled=ag_detected,
                    is_detected=ag_brain.exists(),
                    detection_info="~/.gemini/antigravity-ide"
                ),
                SubItemMeta(
                    id="antigravity_cache",
                    name="Local App State & Cache",
                    description="Runtime cache and local staging in AppData/Local/antigravity.",
                    category="Cache",
                    admin_required_restore=False,
                    default_enabled=ag_detected,
                    is_detected=bool(ag_local and ag_local.exists()),
                    detection_info="AppData/Local"
                )
            ]
        ),

        AppGroupMeta(
            id="group_vscode",
            name="Visual Studio Code",
            icon="💻",
            software_family="IDEs & Code Editors",
            is_detected=vscode_detected,
            detection_info=vscode_info,
            sub_items=[
                SubItemMeta(
                    id="vscode_unsaved",
                    name="Unsaved Files & Workspace Buffers",
                    description="Unsaved editor buffer backups, untitled files, and workspace storage in AppData/Roaming/Code/Backups.",
                    category="Unsaved Files",
                    admin_required_restore=False,
                    default_enabled=vscode_detected,
                    is_detected=vscode_detected,
                    detection_info="Backups & Workspaces"
                ),
                SubItemMeta(
                    id="vscode_settings",
                    name="Settings, Theme & UI Layout",
                    description="settings.json (Activity Bar position, color themes, keybindings), globalStorage (state.vscdb layout database), snippets, and local history.",
                    category="Configuration",
                    admin_required_restore=False,
                    default_enabled=vscode_detected,
                    is_detected=vscode_detected,
                    detection_info="settings.json & state.vscdb"
                ),
                SubItemMeta(
                    id="vscode_extensions",
                    name="Extensions & Profile Sync",
                    description="Installed extension metadata and profile configurations (~/.vscode/extensions).",
                    category="Extensions",
                    admin_required_restore=False,
                    default_enabled=vscode_detected,
                    is_detected=(userprofile / ".vscode").exists(),
                    detection_info="~/.vscode"
                )
            ]
        ),

        AppGroupMeta(
            id="group_notepadpp",
            name="Notepad++",
            icon="📝",
            software_family="IDEs & Code Editors",
            is_detected=npp_detected,
            detection_info=npp_info,
            sub_items=[
                SubItemMeta(
                    id="notepadpp_unsaved",
                    name="Unsaved Files & Periodic Backups",
                    description="Unsaved document buffers (AppData/Roaming/Notepad++/backup) and active session tabs (session.xml).",
                    category="Unsaved Files",
                    admin_required_restore=False,
                    default_enabled=npp_detected,
                    is_detected=npp_unsaved_detected,
                    detection_info="backup & session.xml"
                ),
                SubItemMeta(
                    id="notepadpp_config",
                    name="Settings, Plugins & Shortcuts",
                    description="User preferences (config.xml), custom shortcuts (shortcuts.xml), syntax styling, and plugin configs.",
                    category="Configuration",
                    admin_required_restore=False,
                    default_enabled=npp_detected,
                    is_detected=npp_path.exists(),
                    detection_info="config.xml"
                )
            ]
        ),

        # ==========================================
        # Software Family: Web Browsers
        # ==========================================
        AppGroupMeta(
            id="group_chrome",
            name="Google Chrome",
            icon="🌐",
            software_family="Web Browsers",
            is_detected=chrome_detected,
            detection_info=chrome_info,
            sub_items=[
                SubItemMeta(
                    id="chrome_bookmarks",
                    name="Bookmarks & Reading Lists",
                    description="Saved bookmarks across all Chrome profiles.",
                    category="Bookmarks",
                    admin_required_restore=False,
                    default_enabled=chrome_detected,
                    is_detected=chrome_detected,
                    detection_info="Bookmarks"
                ),
                SubItemMeta(
                    id="chrome_extensions",
                    name="Extensions & Profile Preferences",
                    description="Extension storage, sync settings, profile preferences, and session data.",
                    category="Preferences & Extensions",
                    admin_required_restore=False,
                    default_enabled=chrome_detected,
                    is_detected=chrome_detected,
                    detection_info="Preferences"
                )
            ]
        ),

        AppGroupMeta(
            id="group_edge",
            name="Microsoft Edge",
            icon="🌊",
            software_family="Web Browsers",
            is_detected=edge_detected,
            detection_info=edge_info,
            sub_items=[
                SubItemMeta(
                    id="edge_bookmarks",
                    name="Favorites & Reading Lists",
                    description="Saved favorites across Edge profiles.",
                    category="Bookmarks",
                    admin_required_restore=False,
                    default_enabled=edge_detected,
                    is_detected=edge_detected,
                    detection_info="Bookmarks"
                ),
                SubItemMeta(
                    id="edge_extensions",
                    name="Extensions & Profile Preferences",
                    description="Extension local data, sync state, and browser preferences.",
                    category="Preferences & Extensions",
                    admin_required_restore=False,
                    default_enabled=edge_detected,
                    is_detected=edge_detected,
                    detection_info="Preferences"
                )
            ]
        ),

        AppGroupMeta(
            id="group_firefox",
            name="Mozilla Firefox",
            icon="🦊",
            software_family="Web Browsers",
            is_detected=firefox_detected,
            detection_info=firefox_info,
            sub_items=[
                SubItemMeta(
                    id="firefox_bookmarks",
                    name="Bookmarks & History (places.sqlite)",
                    description="Saved bookmarks, history, and favicons database.",
                    category="Bookmarks",
                    admin_required_restore=False,
                    default_enabled=firefox_detected,
                    is_detected=firefox_detected,
                    detection_info="places.sqlite"
                ),
                SubItemMeta(
                    id="firefox_profiles",
                    name="Extensions & Profile Preferences",
                    description="User preferences (prefs.js) and installed extension configurations.",
                    category="Preferences & Extensions",
                    admin_required_restore=False,
                    default_enabled=firefox_detected,
                    is_detected=firefox_detected,
                    detection_info="prefs.js"
                )
            ]
        ),

        # ==========================================
        # Software Family: Office & Productivity
        # ==========================================
        AppGroupMeta(
            id="group_office",
            name="Microsoft Office (Excel, Word, PowerPoint)",
            icon="📊",
            software_family="Office & Productivity",
            is_detected=office_detected,
            detection_info=office_info,
            sub_items=[
                SubItemMeta(
                    id="office_ribbon_qat",
                    name="Ribbon & Quick Access Toolbar (QAT)",
                    description="Custom ribbon tabs, custom user buttons, and Quick Access Toolbar layouts (*.officeUI, *.qat for Excel, Word, PowerPoint).",
                    category="UI Customization",
                    admin_required_restore=False,
                    default_enabled=office_detected,
                    is_detected=office_ui_detected or office_detected,
                    detection_info="*.officeUI & *.qat"
                ),
                SubItemMeta(
                    id="office_templates_macros",
                    name="Templates, XLSTART & Personal Macros",
                    description="Default templates (Normal.dotm), Excel personal macro startup workbooks (XLSTART/PERSONAL.XLSB), and custom themes.",
                    category="Templates & Macros",
                    admin_required_restore=False,
                    default_enabled=office_detected,
                    is_detected=office_templates_detected or office_detected,
                    detection_info="Normal.dotm & XLSTART"
                ),
                SubItemMeta(
                    id="office_dictionaries_signatures",
                    name="Custom Dictionaries & Outlook Signatures",
                    description="Custom spelling dictionary files (CUSTOM.DIC in UProof) and saved Outlook email signatures.",
                    category="Preferences & Proofing",
                    admin_required_restore=False,
                    default_enabled=office_detected,
                    is_detected=office_uproof_detected or office_detected,
                    detection_info="CUSTOM.DIC & Signatures"
                )
            ]
        ),
    ]


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
    
    # 1. System Clock & Multi-Timezones
    if (
        (target_path / "System" / "timezones.reg").exists()
        or (target_path / "System" / "Clock_TimeZone.json").exists()
        or (target_path / "System" / "Clock_TimeDate.json").exists()
        or (target_path / "System" / "Clock_International.json").exists()
    ):
        found_items.append("system_clock")

    # 2. Wi-Fi Network Profiles
    if (
        (target_path / "System" / "wifi_profiles").exists()
        or (target_path / "System" / "WiFi").exists()
    ):
        found_items.append("system_wifi")

    # 3. Dotfiles SSH
    if (
        (target_path / "Dotfiles" / ".ssh").exists()
        or (target_path / "Dotfiles" / "ssh").exists()
    ):
        found_items.append("dotfiles_ssh")

    # 4. Dotfiles Git
    if (
        (target_path / "Dotfiles" / ".gitconfig").exists()
        or (target_path / "Dotfiles" / ".gitignore_global").exists()
    ):
        found_items.append("dotfiles_git")

    # 5. Dotfiles Shell & CLI Configs
    if (
        (target_path / "Dotfiles" / "shell_configs").exists()
        or (target_path / "Dotfiles" / ".bashrc").exists()
        or (target_path / "Dotfiles" / ".zshrc").exists()
        or (target_path / "Dotfiles" / ".config").exists()
        or (target_path / "Dotfiles" / ".aws").exists()
        or (target_path / "Dotfiles" / ".kube").exists()
    ):
        found_items.append("dotfiles_shell")

    # 6. Winget Application Manifest
    if (
        (target_path / "Applications" / "winget-packages.json").exists()
        or (target_path / "Applications" / "winget.json").exists()
    ):
        found_items.append("app_manifest")

    # 7. Antigravity Unsaved Files
    if (
        (target_path / "Antigravity" / "Roaming_IDE" / "Backups").exists()
        or (target_path / "Antigravity" / "Roaming_IDE" / "User" / "workspaceStorage").exists()
        or (target_path / "Antigravity" / "Backups").exists()
        or (target_path / "Antigravity" / "User" / "workspaceStorage").exists()
    ):
        found_items.append("antigravity_unsaved")

    # 8. Antigravity Settings, Theme & Layout
    if (
        (target_path / "Antigravity" / "Roaming_IDE" / "User" / "settings.json").exists()
        or (target_path / "Antigravity" / "Roaming_IDE" / "User" / "globalStorage").exists()
        or (target_path / "Antigravity" / "User" / "settings.json").exists()
        or (target_path / "Antigravity" / "User" / "globalStorage").exists()
    ):
        found_items.append("antigravity_settings")

    # 9. Antigravity Config & Rules
    if (target_path / "Antigravity" / "gemini_config").exists():
        found_items.append("antigravity_config")

    # 10. Antigravity Brain
    if (target_path / "Antigravity" / "gemini_ide").exists():
        found_items.append("antigravity_brain")

    # 11. Antigravity Local App Data Cache
    if (target_path / "Antigravity" / "local_appdata").exists():
        found_items.append("antigravity_cache")

    # 12. VS Code Unsaved Buffers
    if (
        (target_path / "VSCode" / "Backups").exists()
        or (target_path / "VSCode" / "User" / "workspaceStorage").exists()
    ):
        found_items.append("vscode_unsaved")

    # 13. VS Code Settings, Theme & Layout
    if (
        (target_path / "VSCode" / "User" / "settings.json").exists()
        or (target_path / "VSCode" / "User" / "globalStorage").exists()
    ):
        found_items.append("vscode_settings")

    # 14. VS Code Extensions
    if (
        (target_path / "VSCode" / "extensions").exists()
        or (target_path / "VSCode" / "extensions.json").exists()
    ):
        found_items.append("vscode_extensions")

    # 15. Notepad++ Unsaved Files & Sessions
    if (
        (target_path / "Notepad++" / "backup").exists()
        or (target_path / "Notepad++" / "session.xml").exists()
    ):
        found_items.append("notepadpp_unsaved")

    # 16. Notepad++ Config & Plugins
    if (
        (target_path / "Notepad++" / "config.xml").exists()
        or (target_path / "Notepad++" / "shortcuts.xml").exists()
        or (target_path / "Notepad++" / "plugins").exists()
    ):
        found_items.append("notepadpp_config")
    
    # 17 & 18. Chrome Bookmarks & Extensions
    chrome_dir = target_path / "Chrome"
    if chrome_dir.exists() and chrome_dir.is_dir():
        try:
            for p in chrome_dir.iterdir():
                if p.is_dir():
                    if (p / "Bookmarks").exists() and "chrome_bookmarks" not in found_items:
                        found_items.append("chrome_bookmarks")
                    if ((p / "Preferences").exists() or (p / "Local Extension Settings").exists() or (p / "Sync Extension Settings").exists()) and "chrome_extensions" not in found_items:
                        found_items.append("chrome_extensions")
        except OSError:
            pass

    # 19 & 20. Edge Bookmarks & Extensions
    edge_dir = target_path / "Edge"
    if edge_dir.exists() and edge_dir.is_dir():
        try:
            for p in edge_dir.iterdir():
                if p.is_dir():
                    if (p / "Bookmarks").exists() and "edge_bookmarks" not in found_items:
                        found_items.append("edge_bookmarks")
                    if ((p / "Preferences").exists() or (p / "Local Extension Settings").exists() or (p / "Sync Extension Settings").exists()) and "edge_extensions" not in found_items:
                        found_items.append("edge_extensions")
        except OSError:
            pass

    # 21 & 22. Firefox Bookmarks & Preferences
    ff_dir = target_path / "Firefox"
    if ff_dir.exists() and ff_dir.is_dir():
        try:
            for p in ff_dir.iterdir():
                if p.is_dir():
                    if ((p / "places.sqlite").exists() or (p / "favicons.sqlite").exists()) and "firefox_bookmarks" not in found_items:
                        found_items.append("firefox_bookmarks")
                    if ((p / "prefs.js").exists() or (p / "extensions").exists() or (p / "extension-settings").exists()) and "firefox_profiles" not in found_items:
                        found_items.append("firefox_profiles")
        except OSError:
            pass

    # 23, 24, 25. Microsoft Office (Excel, Word, PowerPoint)
    if (target_path / "Office" / "UI").exists():
        found_items.append("office_ribbon_qat")
    if (
        (target_path / "Office" / "Templates").exists()
        or (target_path / "Office" / "Excel_XLSTART").exists()
        or (target_path / "Office" / "Word_STARTUP").exists()
    ):
        found_items.append("office_templates_macros")
    if (
        (target_path / "Office" / "UProof").exists()
        or (target_path / "Office" / "Signatures").exists()
    ):
        found_items.append("office_dictionaries_signatures")

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
