import os
import shutil
import stat
import subprocess
import json
import winreg
import ctypes
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

# central metadata mapping group ID to human-readable info
GROUP_METADATA = {
    "group_system": {
        "name": "Windows Settings",
        "icon": "🌐",
        "software_family": "System Info",
        "detection_info": "Windows Registry",
    },
    "group_developer": {
        "name": "Developer Dotfiles",
        "icon": "🐚",
        "software_family": "System Info",
        "detection_info": "User Profile",
    },
    "group_antigravity": {
        "name": "Antigravity AI Platform",
        "icon": "✨",
        "software_family": "IDEs & Code Editors",
    },
    "group_vscode": {
        "name": "Visual Studio Code",
        "icon": "💻",
        "software_family": "IDEs & Code Editors",
    },
    "group_notepadpp": {
        "name": "Notepad++",
        "icon": "📝",
        "software_family": "IDEs & Code Editors",
    },
    "group_chrome": {
        "name": "Google Chrome",
        "icon": "🌐",
        "software_family": "Web Browsers",
    },
    "group_edge": {
        "name": "Microsoft Edge",
        "icon": "🌊",
        "software_family": "Web Browsers",
    },
    "group_firefox": {
        "name": "Mozilla Firefox",
        "icon": "🦊",
        "software_family": "Web Browsers",
    },
    "group_office": {
        "name": "Microsoft Office (Excel, Word, PowerPoint)",
        "icon": "📊",
        "software_family": "Office & Productivity",
    },
}

# --- Shared Helpers ---

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def robust_copy_file(src: Path, dest: Path) -> bool:
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
    except Exception:
        return False

def robust_copytree(src: Path, dest: Path):
    if not src.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel_path = Path(root).relative_to(src)
        target_dir = dest / rel_path
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith(('.tmp', '.lock', '.sock', '.pid', '.ldb.lock')):
                continue
            robust_copy_file(Path(root) / f, target_dir / f)

def safe_terminate_process(image_name: str, log_fn: Optional[Callable[[str], None]] = None):
    """Safely terminate a running process during restore if running, bypassing during tests."""
    if os.environ.get("MIGRATOR_TESTING") == "1":
        return
    try:
        check = subprocess.run(f'tasklist /FI "IMAGENAME eq {image_name}"', shell=True, capture_output=True, text=True)
        if image_name.lower() in check.stdout.lower():
            if log_fn:
                log_fn(f"Closing active {image_name} tasks to release file locks...")
            subprocess.run(f"taskkill /IM {image_name} /T", shell=True, capture_output=True)
    except Exception:
        pass

def get_antigravity_roaming_path() -> Optional[Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    for candidate in ["Antigravity IDE", "Antigravity", "antigravity"]:
        p = appdata / candidate
        if p.exists():
            return p
    return appdata / "Antigravity IDE"

def get_antigravity_local_path() -> Optional[Path]:
    localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    for candidate in ["antigravity", "Antigravity", "Antigravity IDE"]:
        p = localappdata / candidate
        if p.exists():
            return p
    return localappdata / "antigravity"

# --- Registry Import/Export Utilities ---

def export_registry_key_tree(root: int, subkey_path: str) -> Optional[Dict[str, Any]]:
    try:
        key = winreg.OpenKey(root, subkey_path, 0, winreg.KEY_READ)
    except (FileNotFoundError, PermissionError, OSError):
        return None

    data: Dict[str, Any] = {"values": {}, "subkeys": {}}
    try:
        subkeys_count, values_count, _ = winreg.QueryInfoKey(key)
        for i in range(values_count):
            try:
                name, val, val_type = winreg.EnumValue(key, i)
                if isinstance(val, bytes):
                    val = val.hex()
                data["values"][name] = {"val": val, "type": val_type}
            except OSError:
                continue

        for i in range(subkeys_count):
            try:
                sname = winreg.EnumKey(key, i)
                child_data = export_registry_key_tree(root, f"{subkey_path}\\{sname}")
                if child_data is not None:
                    data["subkeys"][sname] = child_data
            except OSError:
                continue
    finally:
        winreg.CloseKey(key)
    return data

def import_registry_key_tree(root: int, subkey_path: str, data: Dict[str, Any], log_fn: Optional[Callable[[str], None]] = None) -> bool:
    try:
        key = winreg.CreateKey(root, subkey_path)
    except PermissionError:
        if log_fn:
            log_fn(f"[Warning] Access denied writing registry key: {subkey_path} (Requires Admin)")
        return False
    except Exception as e:
        if log_fn:
            log_fn(f"[Error] Failed to create/open registry key {subkey_path}: {e}")
        return False

    try:
        for val_name, val_info in data.get("values", {}).items():
            val = val_info.get("val")
            val_type = val_info.get("type", winreg.REG_SZ)
            if val_type == winreg.REG_BINARY and isinstance(val, str):
                try:
                    val = bytes.fromhex(val)
                except ValueError:
                    pass
            try:
                winreg.SetValueEx(key, val_name, 0, val_type, val)
            except Exception as e:
                if log_fn:
                    log_fn(f"[Warning] Failed to set value {val_name} in {subkey_path}: {e}")

        for child_name, child_data in data.get("subkeys", {}).items():
            import_registry_key_tree(root, f"{subkey_path}\\{child_name}", child_data, log_fn)
        return True
    finally:
        winreg.CloseKey(key)

# --- Base Provider ---

class BaseProvider(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def group_id(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def category(self) -> str:
        pass

    @property
    def admin_required_restore(self) -> bool:
        return False

    @property
    def default_enabled(self) -> bool:
        return True

    @property
    def detection_info(self) -> str:
        return "Detected"

    @abstractmethod
    def is_detected(self) -> bool:
        pass

    @abstractmethod
    def is_in_backup(self, backup_root: Path) -> bool:
        pass

    @abstractmethod
    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        pass

    @abstractmethod
    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        pass


class ProviderRegistry:
    _registry: Dict[str, BaseProvider] = {}

    @classmethod
    def register(cls, provider: BaseProvider):
        cls._registry[provider.id] = provider

    @classmethod
    def get(cls, provider_id: str) -> Optional[BaseProvider]:
        return cls._registry.get(provider_id)

    @classmethod
    def all(cls) -> Dict[str, BaseProvider]:
        return cls._registry


# ==========================================
# 1. Windows Settings Providers (group_system)
# ==========================================

class SystemClockProvider(BaseProvider):
    id = "system_clock"
    name = "Clock & Multi-Timezones"
    group_id = "group_system"
    category = "System"
    description = "Additional clocks (AEST, CST), international formatting, and system timezone."
    detection_info = "Registry"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        sys_path = backup_root / "System"
        return (
            (sys_path / "timezones.reg").exists()
            or (sys_path / "Clock_TimeZone.json").exists()
            or (sys_path / "Clock_TimeDate.json").exists()
            or (sys_path / "Clock_International.json").exists()
        )

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        sys_dest = backup_root / "System"
        sys_dest.mkdir(parents=True, exist_ok=True)

        log_fn("Exporting Multi-Timezone Additional Clocks from HKCU\\Control Panel\\TimeDate...")
        timedate_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\TimeDate")
        if timedate_data:
            with open(sys_dest / "Clock_TimeDate.json", "w", encoding="utf-8") as f:
                json.dump(timedate_data, f, indent=2)
            add_clocks = timedate_data.get("subkeys", {}).get("AdditionalClocks", {}).get("subkeys", {})
            clock_summaries = []
            for cid, cinfo in add_clocks.items():
                vals = cinfo.get("values", {})
                enabled = vals.get("Enable", {}).get("val") == 1
                tz_name = vals.get("TzRegKeyName", {}).get("val", "Unknown TZ")
                disp_name = vals.get("DisplayName", {}).get("val", f"Clock {cid}")
                clock_summaries.append(f"Clock {cid}: '{disp_name}' ({tz_name}, {'Enabled' if enabled else 'Disabled'})")
            if clock_summaries:
                log_fn(f"  -> Found {len(clock_summaries)} additional clock(s): {', '.join(clock_summaries)}")
            else:
                log_fn("  -> TimeDate exported (no active additional clocks configured).")

        log_fn("Exporting Regional & Locale formatting from HKCU\\Control Panel\\International...")
        intl_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\International")
        if intl_data:
            with open(sys_dest / "Clock_International.json", "w", encoding="utf-8") as f:
                json.dump(intl_data, f, indent=2)
            locale_name = intl_data.get("values", {}).get("LocaleName", {}).get("val", "Default")
            log_fn(f"  -> International locale settings exported (Locale: {locale_name}).")

        log_fn("Exporting System TimeZone information...")
        tz_data = export_registry_key_tree(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
        if tz_data:
            with open(sys_dest / "Clock_TimeZone.json", "w", encoding="utf-8") as f:
                json.dump(tz_data, f, indent=2)
            tz_name = tz_data.get("values", {}).get("TimeZoneKeyName", {}).get("val", "Unknown")
            log_fn(f"  -> System Timezone exported ({tz_name}).")
        return True

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        sys_src = backup_root / "System"
        
        # 1. Multi-timezone Additional Clocks
        clocks_file = sys_src / "Clock_TimeDate.json"
        if clocks_file.exists():
            log_fn("Restoring Multi-Timezone Additional Clocks to HKCU\\Control Panel\\TimeDate...")
            try:
                with open(clocks_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\TimeDate", data, log_fn)
            except Exception as e:
                log_fn(f"  -> Error restoring Clocks: {e}")

        # 2. Locale Formats
        intl_file = sys_src / "Clock_International.json"
        if intl_file.exists():
            log_fn("Restoring Regional & Locale formatting to HKCU\\Control Panel\\International...")
            try:
                with open(intl_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\International", data, log_fn)
            except Exception as e:
                log_fn(f"  -> Error restoring Locale: {e}")

        # 3. System TimeZone
        tz_file = sys_src / "Clock_TimeZone.json"
        if tz_file.exists():
            log_fn("Restoring System Timezone setting...")
            try:
                with open(tz_file, "r", encoding="utf-8") as f:
                    tz_data = json.load(f)
                tz_name = tz_data.get("values", {}).get("TimeZoneKeyName", {}).get("val")
                if tz_name:
                    log_fn(f"  -> Attempting to set system timezone to '{tz_name}' via tzutil...")
                    res = subprocess.run(f'tzutil /s "{tz_name}"', shell=True, capture_output=True, text=True)
                    if res.returncode == 0:
                        log_fn(f"  -> System timezone set to '{tz_name}'.")
                    else:
                        log_fn(f"  -> Note: tzutil returned code {res.returncode}. (Setting system timezone requires admin)")
            except Exception as e:
                log_fn(f"  -> Error setting TimeZone: {e}")
        return True


class WiFiProvider(BaseProvider):
    id = "system_wifi"
    name = "Wi-Fi Network Profiles"
    group_id = "group_system"
    category = "Networking"
    description = "Saved Wi-Fi profiles & security keys. (Restoring system-wide requires Admin)"
    admin_required_restore = True
    detection_info = "netsh WLAN"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        sys_path = backup_root / "System"
        return (sys_path / "wifi_profiles").exists() or (sys_path / "WiFi").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        wifi_dest = backup_root / "System" / "WiFi"
        wifi_dest.mkdir(parents=True, exist_ok=True)
        log_fn("Exporting Wi-Fi profiles via netsh...")
        subprocess.run(
            f'netsh wlan export profile folder="{wifi_dest}" key=clear',
            shell=True,
            capture_output=True,
            text=True
        )
        xml_count = len(list(wifi_dest.glob("*.xml")))
        log_fn(f"  -> Exported {xml_count} Wi-Fi profile(s).")
        return True

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        wifi_dir = backup_root / "System" / "WiFi"
        if not wifi_dir.exists():
            wifi_dir = backup_root / "System" / "wifi_profiles"  # legacy compatibility
        if wifi_dir.exists():
            xml_files = list(wifi_dir.glob("*.xml"))
            log_fn(f"Importing {len(xml_files)} Wi-Fi profile(s)...")
            for xml in xml_files:
                res = subprocess.run(
                    f'netsh wlan add profile filename="{xml}" user=all',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if res.returncode == 0:
                    log_fn(f"  -> Added Wi-Fi profile: {xml.stem}")
                else:
                    log_fn(f"  -> Adding {xml.stem} returned code {res.returncode}. (May require Admin/Elevation)")
            return True
        log_fn("  -> No Wi-Fi profiles found in backup.")
        return False


class WingetManifestProvider(BaseProvider):
    id = "app_manifest"
    name = "Winget Application Manifest/List"
    group_id = "group_system"
    category = "Package Manager"
    description = "Inventory of installed Windows software for automated batch reinstallation."
    admin_required_restore = True
    detection_info = "winget.json"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        apps_path = backup_root / "Applications"
        return (apps_path / "winget-packages.json").exists() or (apps_path / "winget.json").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        apps_dest = backup_root / "Applications"
        apps_dest.mkdir(parents=True, exist_ok=True)
        manifest_file = apps_dest / "winget-packages.json"
        log_fn("Exporting Winget package manifest...")
        subprocess.run(
            f'winget export -o "{manifest_file}" --accept-source-agreements',
            shell=True,
            capture_output=True,
            text=True
        )
        if manifest_file.exists():
            log_fn(f"  -> Winget package list exported.")
            return True
        log_fn("  -> Winget manifest export failed.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        manifest = backup_root / "Applications" / "winget-packages.json"
        if not manifest.exists():
            manifest = backup_root / "Applications" / "winget.json"
        if manifest.exists():
            log_fn("Restoring applications via Winget import...")
            res = subprocess.run(
                f'winget import -i "{manifest}" --accept-package-agreements --accept-source-agreements',
                shell=True,
                capture_output=True,
                text=True
            )
            log_fn(f"  -> Winget import executed with return code {res.returncode}.")
            return True
        log_fn("  -> No Winget manifest found in backup.")
        return False


class WallpaperProvider(BaseProvider):
    id = "system_wallpaper"
    name = "Desktop Wallpaper"
    group_id = "group_system"
    category = "Personalization"
    description = "Backup current desktop wallpaper image and slideshow settings."
    detection_info = "TranscodedWallpaper & Registry"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        sys_path = backup_root / "System"
        return (sys_path / "Wallpaper").exists() or (sys_path / "Wallpaper_Registry.json").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        log_fn("Backing up current wallpaper configurations...")
        themes_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Themes"
        if themes_dir.exists():
            dest = backup_root / "System" / "Wallpaper"
            robust_copytree(themes_dir, dest)
            log_fn("  -> Copied wallpaper theme files recursively.")

        # Save registry keys
        log_fn("Exporting Wallpaper registry settings...")
        wallpaper_reg = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
        if wallpaper_reg:
            # We filter/keep wallpaper settings to avoid writing unrelated keys
            filtered_vals = {}
            for k in ["Wallpaper", "WallpaperStyle", "TileWallpaper"]:
                if k in wallpaper_reg.get("values", {}):
                    filtered_vals[k] = wallpaper_reg["values"][k]
            
            reg_filtered = {"values": filtered_vals, "subkeys": {}}
            with open(backup_root / "System" / "Wallpaper_Registry.json", "w", encoding="utf-8") as f:
                json.dump(reg_filtered, f, indent=2)
            log_fn("  -> Exported core desktop wallpaper registry settings.")

        slideshow_reg = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\Personalization\Desktop Slideshow")
        if slideshow_reg:
            with open(backup_root / "System" / "Wallpaper_Slideshow_Registry.json", "w", encoding="utf-8") as f:
                json.dump(slideshow_reg, f, indent=2)
            log_fn("  -> Exported wallpaper slideshow registry settings.")
        return True

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        log_fn("Restoring desktop wallpaper files...")
        themes_dest = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Themes"
        themes_src = backup_root / "System" / "Wallpaper"
        if themes_src.exists():
            robust_copytree(themes_src, themes_dest)
            log_fn("  -> Restored wallpaper files to user themes.")

        reg_file = backup_root / "System" / "Wallpaper_Registry.json"
        if reg_file.exists():
            try:
                with open(reg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", data, log_fn)
            except Exception as e:
                log_fn(f"  [Warning] Error restoring wallpaper registry settings: {e}")

        slideshow_file = backup_root / "System" / "Wallpaper_Slideshow_Registry.json"
        if slideshow_file.exists():
            try:
                with open(slideshow_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\Personalization\Desktop Slideshow", data, log_fn)
            except Exception as e:
                log_fn(f"  [Warning] Error restoring slideshow registry: {e}")

        # Programmatically refresh wallpaper
        SPI_SETDESKWALLPAPER = 20
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDCHANGE = 0x02
        transcoded_path = themes_dest / "TranscodedWallpaper"
        if transcoded_path.exists():
            try:
                # Force registry to point directly to transcoded wallpaper to guarantee load
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "Wallpaper", 0, winreg.REG_SZ, str(transcoded_path))
                winreg.CloseKey(key)
                log_fn(f"  -> Registry Wallpaper path set to: {transcoded_path}")
            except Exception as reg_err:
                log_fn(f"  [Warning] Failed writing registry Wallpaper path: {reg_err}")

            log_fn("Broadcasting wallpaper refresh notification to Windows...")
            try:
                res = ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, str(transcoded_path), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
                log_fn(f"  -> SystemParametersInfoW completed with status: {res}")
            except Exception as refresh_err:
                log_fn(f"  [Warning] Failed calling SystemParametersInfoW: {refresh_err}")
        else:
            log_fn("  -> Restored themes folder did not contain TranscodedWallpaper file.")
        return True


class ExplorerSettingsProvider(BaseProvider):
    id = "system_explorer"
    name = "File Explorer Settings"
    group_id = "group_system"
    category = "System Customization"
    description = "User preferences for File Explorer (show hidden files, show file extensions, and folder options)."
    detection_info = "Registry"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        sys_path = backup_root / "System"
        return (sys_path / "Explorer_Advanced.json").exists() or (sys_path / "Explorer_CabinetState.json").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        sys_dest = backup_root / "System"
        sys_dest.mkdir(parents=True, exist_ok=True)

        log_fn("Exporting Explorer Advanced settings...")
        adv_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced")
        if adv_data:
            with open(sys_dest / "Explorer_Advanced.json", "w", encoding="utf-8") as f:
                json.dump(adv_data, f, indent=2)
            log_fn("  -> Exported Explorer Advanced registry tree.")

        log_fn("Exporting Explorer CabinetState settings...")
        cab_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\CabinetState")
        if cab_data:
            with open(sys_dest / "Explorer_CabinetState.json", "w", encoding="utf-8") as f:
                json.dump(cab_data, f, indent=2)
            log_fn("  -> Exported Explorer CabinetState registry tree.")
        return True

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        sys_src = backup_root / "System"

        adv_file = sys_src / "Explorer_Advanced.json"
        if adv_file.exists():
            log_fn("Restoring Explorer Advanced settings...")
            try:
                with open(adv_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", data, log_fn)
            except Exception as e:
                log_fn(f"  [Warning] Error restoring Explorer Advanced settings: {e}")

        cab_file = sys_src / "Explorer_CabinetState.json"
        if cab_file.exists():
            log_fn("Restoring Explorer CabinetState settings...")
            try:
                with open(cab_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\CabinetState", data, log_fn)
            except Exception as e:
                log_fn(f"  [Warning] Error restoring Explorer CabinetState: {e}")

        # Broadcast shell settings change to update explorer.exe window dynamically
        log_fn("Broadcasting Shell change notifications to refresh File Explorer...")
        try:
            # HWND_BROADCAST = 0xFFFF, WM_SETTINGCHANGE = 0x001A
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "TraySettings")
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "Policy")
            # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
            log_fn("  -> Sent shell notifications. (Note: Some changes may require restarting open explorer windows or logging out to take full effect).")
        except Exception as msg_err:
            log_fn(f"  [Warning] Failed broadcasting system change messages: {msg_err}")
        return True


# ==========================================
# 2. Developer Dotfiles (group_developer)
# ==========================================

class SSHKeysProvider(BaseProvider):
    id = "dotfiles_ssh"
    name = "SSH Keys & Known Hosts (~/.ssh)"
    group_id = "group_developer"
    category = "Security"
    description = "SSH keypairs, known_hosts, and client configs."
    detection_info = "~/.ssh"

    def is_detected(self) -> bool:
        return (Path.home() / ".ssh").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        dot_path = backup_root / "Dotfiles"
        return (dot_path / ".ssh").exists() or (dot_path / "ssh").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = Path.home() / ".ssh"
        if src.exists():
            dest = backup_root / "Dotfiles" / ".ssh"
            robust_copytree(src, dest)
            log_fn("  -> Backed up SSH key directories recursively.")
            return True
        log_fn("  -> SSH config folder not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Dotfiles" / ".ssh"
        if not src.exists():
            src = backup_root / "Dotfiles" / "ssh"
        if src.exists():
            dest = Path.home() / ".ssh"
            robust_copytree(src, dest)
            log_fn("  -> Restored ~/.ssh keys.")
            return True
        log_fn("  -> No SSH files found in backup.")
        return False


class GitConfigProvider(BaseProvider):
    id = "dotfiles_git"
    name = "Git Configuration (~/.gitconfig)"
    group_id = "group_developer"
    category = "Version Control"
    description = "Global git user settings, credential helpers, and global ignores."
    detection_info = "~/.gitconfig"

    def is_detected(self) -> bool:
        return (Path.home() / ".gitconfig").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        dot_path = backup_root / "Dotfiles"
        return (dot_path / ".gitconfig").exists() or (dot_path / ".gitignore_global").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        dest = backup_root / "Dotfiles"
        dest.mkdir(parents=True, exist_ok=True)
        backed_up = False
        for g in [".gitconfig", ".gitignore_global"]:
            src = Path.home() / g
            if src.exists():
                robust_copy_file(src, dest / g)
                log_fn(f"  -> Backed up {g}")
                backed_up = True
        return backed_up

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Dotfiles"
        restored = False
        for g in [".gitconfig", ".gitignore_global"]:
            if (src / g).exists():
                robust_copy_file(src / g, Path.home() / g)
                log_fn(f"  -> Restored {g}")
                restored = True
        return restored


class ShellConfigsProvider(BaseProvider):
    id = "dotfiles_shell"
    name = "Shell & Cloud CLI Configs"
    group_id = "group_developer"
    category = "Shell Environment"
    description = "Configs in ~/.config, ~/.bashrc, ~/.zshrc, ~/.aws, ~/.kube."
    detection_info = "~/.config"

    def is_detected(self) -> bool:
        return True

    def is_in_backup(self, backup_root: Path) -> bool:
        dot_path = backup_root / "Dotfiles"
        for s in [".bash_profile", ".bashrc", ".zshrc", ".config", ".aws", ".kube", "shell_configs"]:
            if (dot_path / s).exists():
                return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        dest = backup_root / "Dotfiles"
        dest.mkdir(parents=True, exist_ok=True)
        count = 0
        for s in [".bash_profile", ".bashrc", ".zshrc", ".config", ".aws", ".kube"]:
            src = Path.home() / s
            if src.exists():
                if src.is_dir():
                    robust_copytree(src, dest / s)
                else:
                    robust_copy_file(src, dest / s)
                log_fn(f"  -> Backed up {s}")
                count += 1
        return count > 0

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Dotfiles"
        if not src.exists():
            src = backup_root / "Dotfiles" / "shell_configs"  # legacy compatibility
        restored = False
        for s in [".bash_profile", ".bashrc", ".zshrc", ".config", ".aws", ".kube"]:
            s_src = src / s
            if s_src.exists():
                if s_src.is_dir():
                    robust_copytree(s_src, Path.home() / s)
                else:
                    robust_copy_file(s_src, Path.home() / s)
                log_fn(f"  -> Restored {s}")
                restored = True
        return restored


# ==========================================
# 3. Antigravity IDE (group_antigravity)
# ==========================================

class AntigravityUnsavedProvider(BaseProvider):
    id = "antigravity_unsaved"
    name = "Unsaved Files & Workspace Buffers"
    group_id = "group_antigravity"
    category = "Unsaved Files"
    description = "Active unsaved files, untitled scratch tabs, and hot exit backups in AppData/Roaming/Antigravity IDE/Backups."
    detection_info = "Backups & Sessions"

    def is_detected(self) -> bool:
        ag_roaming = get_antigravity_roaming_path()
        return bool(ag_roaming and ((ag_roaming / "Backups").exists() or (ag_roaming / "User" / "workspaceStorage").exists()))

    def is_in_backup(self, backup_root: Path) -> bool:
        ag_path = backup_root / "Antigravity"
        return (
            (ag_path / "Roaming_IDE" / "Backups").exists()
            or (ag_path / "Roaming_IDE" / "User" / "workspaceStorage").exists()
            or (ag_path / "Backups").exists()
            or (ag_path / "User" / "workspaceStorage").exists()
        )

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        ag_roaming = get_antigravity_roaming_path()
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
            log_fn("  -> Saved Antigravity hot exit buffers and workspace storage.")
            return True
        log_fn("  -> No unsaved files found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Antigravity" / "Roaming_IDE"
        if not src.exists():
            src = backup_root / "Antigravity"  # legacy path compatibility
        ag_roaming = get_antigravity_roaming_path()
        if src.exists() and ag_roaming:
            if (src / "Backups").exists():
                robust_copytree(src / "Backups", ag_roaming / "Backups")
            if (src / "User" / "workspaceStorage").exists():
                robust_copytree(src / "User" / "workspaceStorage", ag_roaming / "User" / "workspaceStorage")
            log_fn("  -> Restored Antigravity unsaved editor buffers.")
            return True
        log_fn("  -> No backup files to restore.")
        return False


class AntigravitySettingsProvider(BaseProvider):
    id = "antigravity_settings"
    name = "Settings, Theme & UI Layout"
    group_id = "group_antigravity"
    category = "Configuration"
    description = "settings.json (Activity Bar position, color themes, fonts), keybindings.json, globalStorage (state.vscdb layout database), and snippets."
    detection_info = "settings.json & state.vscdb"

    def is_detected(self) -> bool:
        ag_roaming = get_antigravity_roaming_path()
        return bool(ag_roaming and (ag_roaming / "User").exists())

    def is_in_backup(self, backup_root: Path) -> bool:
        ag_path = backup_root / "Antigravity"
        return (
            (ag_path / "Roaming_IDE" / "User" / "settings.json").exists()
            or (ag_path / "User" / "settings.json").exists()
        )

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        ag_roaming = get_antigravity_roaming_path()
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
            log_fn("  -> Saved Antigravity theme, layout database, and keybindings.")
            return True
        log_fn("  -> Antigravity settings folder not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Antigravity" / "Roaming_IDE" / "User"
        if not src.exists():
            src = backup_root / "Antigravity" / "User"
        ag_roaming = get_antigravity_roaming_path()
        if src.exists() and ag_roaming:
            robust_copytree(src, ag_roaming / "User")
            log_fn("  -> Restored Antigravity settings & snippet UI layout configurations.")
            return True
        log_fn("  -> Antigravity settings backup not found.")
        return False


class AntigravityConfigProvider(BaseProvider):
    id = "antigravity_config"
    name = "Rules, Skills & Plugins"
    group_id = "group_antigravity"
    category = "Customizations"
    description = "Global custom skills, behavioral rules, and plugin configs in ~/.gemini/config."
    detection_info = "~/.gemini/config"

    def is_detected(self) -> bool:
        return (Path.home() / ".gemini" / "config").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "Antigravity" / "gemini_config").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = Path.home() / ".gemini" / "config"
        if src.exists():
            dest = backup_root / "Antigravity" / "gemini_config"
            robust_copytree(src, dest)
            log_fn("  -> Backed up custom rules, skills, and plugins.")
            return True
        log_fn("  -> Gemini global config folder not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Antigravity" / "gemini_config"
        if src.exists():
            robust_copytree(src, Path.home() / ".gemini" / "config")
            log_fn("  -> Restored global custom skills and rules.")
            return True
        log_fn("  -> Antigravity config backup folder not found.")
        return False


class AntigravityBrainProvider(BaseProvider):
    id = "antigravity_brain"
    name = "Brain (Conversations & Knowledge)"
    group_id = "group_antigravity"
    category = "Conversations"
    description = "Transcripts, knowledge base, artifacts, conversation trajectories, and tool schemas (~/.gemini/antigravity-ide)."
    detection_info = "~/.gemini/antigravity-ide"

    def is_detected(self) -> bool:
        return (Path.home() / ".gemini" / "antigravity-ide").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "Antigravity" / "gemini_ide").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = Path.home() / ".gemini" / "antigravity-ide"
        if src.exists():
            dest = backup_root / "Antigravity" / "gemini_ide"
            robust_copytree(src, dest)
            log_fn("  -> Backed up local AI brain trajectories and knowledge base.")
            return True
        log_fn("  -> Gemini IDE brain folder not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Antigravity" / "gemini_ide"
        if src.exists():
            robust_copytree(src, Path.home() / ".gemini" / "antigravity-ide")
            log_fn("  -> Restored all conversational history & knowledge artifacts.")
            return True
        log_fn("  -> Antigravity brain backup not found.")
        return False


class AntigravityCacheProvider(BaseProvider):
    id = "antigravity_cache"
    name = "Local App State & Cache"
    group_id = "group_antigravity"
    category = "Cache"
    description = "Runtime cache and local staging in AppData/Local/antigravity."
    detection_info = "AppData/Local"

    def is_detected(self) -> bool:
        ag_local = get_antigravity_local_path()
        return bool(ag_local and ag_local.exists())

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "Antigravity" / "local_appdata").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        ag_local = get_antigravity_local_path()
        if ag_local and ag_local.exists():
            dest = backup_root / "Antigravity" / "local_appdata"
            robust_copytree(ag_local, dest)
            log_fn("  -> Saved local app data cache.")
            return True
        log_fn("  -> Antigravity local app cache not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "Antigravity" / "local_appdata"
        ag_local = get_antigravity_local_path()
        if src.exists() and ag_local:
            robust_copytree(src, ag_local)
            log_fn("  -> Restored local app cache.")
            return True
        log_fn("  -> Local app data cache backup not found.")
        return False


# ==========================================
# 4. VS Code IDE (group_vscode)
# ==========================================

class VSCodeUnsavedProvider(BaseProvider):
    id = "vscode_unsaved"
    name = "Unsaved Files & Workspace Buffers"
    group_id = "group_vscode"
    category = "Unsaved Files"
    description = "Unsaved editor buffer backups, untitled files, and workspace storage in AppData/Roaming/Code/Backups."
    detection_info = "Backups & Workspaces"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        return (appdata / "Code" / "Backups").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        vscode_path = backup_root / "VSCode"
        return (vscode_path / "Backups").exists() or (vscode_path / "User" / "workspaceStorage").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Saved VS Code unsaved buffers and workspace storage.")
            return True
        log_fn("  -> No VS Code unsaved document buffers found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        src = backup_root / "VSCode"
        restored = False
        if (src / "Backups").exists():
            robust_copytree(src / "Backups", appdata / "Code" / "Backups")
            restored = True
        if (src / "User" / "workspaceStorage").exists():
            robust_copytree(src / "User" / "workspaceStorage", appdata / "Code" / "User" / "workspaceStorage")
            restored = True
        if restored:
            log_fn("  -> Restored VS Code workspace state & unsaved edit cache.")
        return restored


class VSCodeSettingsProvider(BaseProvider):
    id = "vscode_settings"
    name = "Settings, Theme & UI Layout"
    group_id = "group_vscode"
    category = "Configuration"
    description = "settings.json (Activity Bar position, color themes, keybindings), globalStorage (state.vscdb layout database), snippets, and local history."
    detection_info = "settings.json & state.vscdb"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        return (appdata / "Code" / "User").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "VSCode" / "User" / "settings.json").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Backed up VS Code keymaps, theme settings, and layout history.")
            return True
        log_fn("  -> VS Code user config directory not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        src = backup_root / "VSCode" / "User"
        if src.exists():
            robust_copytree(src, appdata / "Code" / "User")
            log_fn("  -> Restored VS Code user preferences, hotkeys, and history.")
            return True
        log_fn("  -> No VS Code user settings found in backup.")
        return False


class VSCodeExtensionsProvider(BaseProvider):
    id = "vscode_extensions"
    name = "Extensions & Profile Sync"
    group_id = "group_vscode"
    category = "Extensions"
    description = "Installed extension metadata and profile configurations (~/.vscode/extensions)."
    detection_info = "~/.vscode"

    def is_detected(self) -> bool:
        return (Path.home() / ".vscode").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "VSCode" / "extensions").exists() or (backup_root / "VSCode" / "extensions.json").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = Path.home() / ".vscode" / "extensions"
        if src.exists():
            dest = backup_root / "VSCode" / "extensions"
            robust_copytree(src, dest)
            log_fn("  -> Saved VS Code extensions inventory.")
            return True
        log_fn("  -> VS Code extensions folder not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        src = backup_root / "VSCode" / "extensions"
        if src.exists():
            robust_copytree(src, Path.home() / ".vscode" / "extensions")
            log_fn("  -> Restored VS Code plugins.")
            return True
        log_fn("  -> VS Code extensions not found in backup.")
        return False


# ==========================================
# 5. Notepad++ (group_notepadpp)
# ==========================================

class NotepadppUnsavedProvider(BaseProvider):
    id = "notepadpp_unsaved"
    name = "Unsaved Files & Periodic Backups"
    group_id = "group_notepadpp"
    category = "Unsaved Files"
    description = "Unsaved document buffers (AppData/Roaming/Notepad++/backup) and active session tabs (session.xml)."
    detection_info = "backup & session.xml"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        npp_path = appdata / "Notepad++"
        return bool(npp_path.exists() and ((npp_path / "backup").exists() or (npp_path / "session.xml").exists()))

    def is_in_backup(self, backup_root: Path) -> bool:
        npp_path = backup_root / "Notepad++"
        return (npp_path / "backup").exists() or (npp_path / "session.xml").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Saved Notepad++ unsaved documents and active session tab layout.")
            return True
        log_fn("  -> Notepad++ unsaved buffers not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        src = backup_root / "Notepad++"
        npp_dest = appdata / "Notepad++"
        restored = False
        if src.exists():
            if (src / "backup").exists():
                robust_copytree(src / "backup", npp_dest / "backup")
                restored = True
            if (src / "session.xml").exists():
                robust_copy_file(src / "session.xml", npp_dest / "session.xml")
                restored = True
        if restored:
            log_fn("  -> Restored Notepad++ unsaved tabs.")
        return restored


class NotepadppConfigProvider(BaseProvider):
    id = "notepadpp_config"
    name = "Settings, Plugins & Shortcuts"
    group_id = "group_notepadpp"
    category = "Configuration"
    description = "User preferences (config.xml), custom shortcuts (shortcuts.xml), syntax styling, and plugin configs."
    detection_info = "config.xml"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        return (appdata / "Notepad++").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "Notepad++" / "config.xml").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        npp_dir = appdata / "Notepad++"
        dest = backup_root / "Notepad++"
        if npp_dir.exists():
            dest.mkdir(parents=True, exist_ok=True)
            for f in ["config.xml", "shortcuts.xml", "contextMenu.xml", "userDefineLang.xml", "stylers.xml"]:
                if (npp_dir / f).exists():
                    robust_copy_file(npp_dir / f, dest / f)
            if (npp_dir / "plugins").exists():
                robust_copytree(npp_dir / "plugins", dest / "plugins")
            log_fn("  -> Saved Notepad++ user configurations, hotkeys, and plugins.")
            return True
        log_fn("  -> Notepad++ app configs not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        src = backup_root / "Notepad++"
        npp_dest = appdata / "Notepad++"
        if src.exists():
            for f in ["config.xml", "shortcuts.xml", "contextMenu.xml", "userDefineLang.xml", "stylers.xml"]:
                if (src / f).exists():
                    robust_copy_file(src / f, npp_dest / f)
            if (src / "plugins").exists():
                robust_copytree(src / "plugins", npp_dest / "plugins")
            log_fn("  -> Restored Notepad++ preferences.")
            return True
        log_fn("  -> Notepad++ backup config folder not found.")
        return False


# ==========================================
# 6. Browsers (group_chrome, group_edge, group_firefox)
# ==========================================

class ChromeBookmarksProvider(BaseProvider):
    id = "chrome_bookmarks"
    name = "Bookmarks & Reading Lists"
    group_id = "group_chrome"
    category = "Bookmarks"
    description = "Saved bookmarks across all Chrome profiles."
    detection_info = "Bookmarks"

    def is_detected(self) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        return (localappdata / "Google" / "Chrome" / "User Data").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        chrome_dir = backup_root / "Chrome"
        if chrome_dir.exists() and chrome_dir.is_dir():
            for p in chrome_dir.iterdir():
                if p.is_dir() and (p / "Bookmarks").exists():
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        chrome_src = localappdata / "Google" / "Chrome" / "User Data"
        if chrome_src.exists():
            count = 0
            for prof in chrome_src.iterdir():
                if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                    bm = prof / "Bookmarks"
                    if bm.exists():
                        robust_copy_file(bm, backup_root / "Chrome" / prof.name / "Bookmarks")
                        count += 1
            log_fn(f"  -> Backed up Bookmarks for {count} Chrome profile(s).")
            return count > 0
        log_fn("  -> Chrome installation data not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        chrome_src = backup_root / "Chrome"
        if chrome_src.exists():
            for prof in chrome_src.iterdir():
                if (prof / "Bookmarks").exists():
                    dest = localappdata / "Google" / "Chrome" / "User Data" / prof.name / "Bookmarks"
                    robust_copy_file(prof / "Bookmarks", dest)
            log_fn("  -> Restored Chrome user bookmarks.")
            return True
        log_fn("  -> Chrome bookmarks backup not found.")
        return False


class ChromeExtensionsProvider(BaseProvider):
    id = "chrome_extensions"
    name = "Extensions & Profile Preferences"
    group_id = "group_chrome"
    category = "Preferences & Extensions"
    description = "Extension storage, sync settings, profile preferences, and session data."
    detection_info = "Preferences"

    def is_detected(self) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        return (localappdata / "Google" / "Chrome" / "User Data").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        chrome_dir = backup_root / "Chrome"
        if chrome_dir.exists() and chrome_dir.is_dir():
            for p in chrome_dir.iterdir():
                if p.is_dir() and ((p / "Preferences").exists() or (p / "Local Extension Settings").exists()):
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        chrome_src = localappdata / "Google" / "Chrome" / "User Data"
        if chrome_src.exists():
            ext_targets = [
                "Local Extension Settings",
                "Sync Extension Settings",
                "DNR Extension Rules",
                "Extension Rules",
                "Extension State",
                "Managed Extension Settings",
            ]
            for prof in chrome_src.iterdir():
                if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                    target = backup_root / "Chrome" / prof.name
                    if (prof / "Preferences").exists():
                        robust_copy_file(prof / "Preferences", target / "Preferences")
                    for ext in ext_targets:
                        if (prof / ext).exists():
                            robust_copytree(prof / ext, target / ext)

            log_fn("  -> Saved Chrome session extensions and settings preferences.")
            return True
        log_fn("  -> Chrome installation data not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        chrome_src = backup_root / "Chrome"
        if chrome_src.exists():
            safe_terminate_process("chrome.exe", log_fn)
            ext_targets = [
                "Local Extension Settings",
                "Sync Extension Settings",
                "DNR Extension Rules",
                "Extension Rules",
                "Extension State",
                "Managed Extension Settings",
            ]
            for prof in chrome_src.iterdir():
                target = localappdata / "Google" / "Chrome" / "User Data" / prof.name
                if (prof / "Preferences").exists():
                    robust_copy_file(prof / "Preferences", target / "Preferences")
                for ext in ext_targets:
                    if (prof / ext).exists():
                        robust_copytree(prof / ext, target / ext)
            log_fn("  -> Restored Chrome settings data.")
            return True
        log_fn("  -> Chrome preferences backup not found.")
        return False


class EdgeBookmarksProvider(BaseProvider):
    id = "edge_bookmarks"
    name = "Favorites & Reading Lists"
    group_id = "group_edge"
    category = "Bookmarks"
    description = "Saved favorites across Edge profiles."
    detection_info = "Bookmarks"

    def is_detected(self) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        return (localappdata / "Microsoft" / "Edge" / "User Data").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        edge_dir = backup_root / "Edge"
        if edge_dir.exists() and edge_dir.is_dir():
            for p in edge_dir.iterdir():
                if p.is_dir() and (p / "Bookmarks").exists():
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        edge_src = localappdata / "Microsoft" / "Edge" / "User Data"
        if edge_src.exists():
            count = 0
            for prof in edge_src.iterdir():
                if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                    bm = prof / "Bookmarks"
                    if bm.exists():
                        robust_copy_file(bm, backup_root / "Edge" / prof.name / "Bookmarks")
                        count += 1
            log_fn(f"  -> Backed up Bookmarks for {count} Microsoft Edge profile(s).")
            return count > 0
        log_fn("  -> Edge installation data not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        edge_src = backup_root / "Edge"
        if edge_src.exists():
            for prof in edge_src.iterdir():
                if (prof / "Bookmarks").exists():
                    dest = localappdata / "Microsoft" / "Edge" / "User Data" / prof.name / "Bookmarks"
                    robust_copy_file(prof / "Bookmarks", dest)
            log_fn("  -> Restored Microsoft Edge user favorites.")
            return True
        log_fn("  -> Edge favorites backup not found.")
        return False


class EdgeExtensionsProvider(BaseProvider):
    id = "edge_extensions"
    name = "Extensions & Profile Preferences"
    group_id = "group_edge"
    category = "Preferences & Extensions"
    description = "Extension local data, sync state, and browser preferences."
    detection_info = "Preferences"

    def is_detected(self) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        return (localappdata / "Microsoft" / "Edge" / "User Data").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        edge_dir = backup_root / "Edge"
        if edge_dir.exists() and edge_dir.is_dir():
            for p in edge_dir.iterdir():
                if p.is_dir() and ((p / "Preferences").exists() or (p / "Local Extension Settings").exists()):
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        edge_src = localappdata / "Microsoft" / "Edge" / "User Data"
        if edge_src.exists():
            ext_targets = [
                "Local Extension Settings",
                "Sync Extension Settings",
                "DNR Extension Rules",
                "Extension Rules",
                "Extension State",
                "Managed Extension Settings",
            ]
            for prof in edge_src.iterdir():
                if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                    target = backup_root / "Edge" / prof.name
                    if (prof / "Preferences").exists():
                        robust_copy_file(prof / "Preferences", target / "Preferences")
                    for ext in ext_targets:
                        if (prof / ext).exists():
                            robust_copytree(prof / ext, target / ext)
            log_fn("  -> Saved Microsoft Edge settings preferences and plugins.")
            return True
        log_fn("  -> Edge installation data not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        edge_src = backup_root / "Edge"
        if edge_src.exists():
            safe_terminate_process("msedge.exe", log_fn)
            ext_targets = [
                "Local Extension Settings",
                "Sync Extension Settings",
                "DNR Extension Rules",
                "Extension Rules",
                "Extension State",
                "Managed Extension Settings",
            ]
            for prof in edge_src.iterdir():
                target = localappdata / "Microsoft" / "Edge" / "User Data" / prof.name
                if (prof / "Preferences").exists():
                    robust_copy_file(prof / "Preferences", target / "Preferences")
                for ext in ext_targets:
                    if (prof / ext).exists():
                        robust_copytree(prof / ext, target / ext)
            log_fn("  -> Restored Edge plugin settings data.")
            return True
        log_fn("  -> Edge preferences backup not found.")
        return False


class FirefoxBookmarksProvider(BaseProvider):
    id = "firefox_bookmarks"
    name = "Bookmarks & History (places.sqlite)"
    group_id = "group_firefox"
    category = "Bookmarks"
    description = "Saved bookmarks, history, and favicons database."
    detection_info = "places.sqlite"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        ff_roaming = appdata / "Mozilla" / "Firefox" / "Profiles"
        ff_local = localappdata / "Mozilla" / "Firefox" / "Profiles"
        return ff_roaming.exists() or ff_local.exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        ff_dir = backup_root / "Firefox"
        if ff_dir.exists() and ff_dir.is_dir():
            for p in ff_dir.iterdir():
                if p.is_dir() and ((p / "places.sqlite").exists() or (p / "favicons.sqlite").exists()):
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
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
            log_fn("  -> Saved Mozilla Firefox bookmarks sqlite database.")
            return True
        log_fn("  -> Firefox profiles not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        ff_src = backup_root / "Firefox"
        if ff_src.exists():
            for prof in ff_src.iterdir():
                target = appdata / "Mozilla" / "Firefox" / "Profiles" / prof.name
                target.mkdir(parents=True, exist_ok=True)
                for f in ["places.sqlite", "favicons.sqlite"]:
                    if (prof / f).exists():
                        robust_copy_file(prof / f, target / f)
            log_fn("  -> Restored Mozilla Firefox bookmarks database.")
            return True
        log_fn("  -> Firefox bookmarks backup not found.")
        return False


class FirefoxProfilesProvider(BaseProvider):
    id = "firefox_profiles"
    name = "Extensions & Profile Preferences"
    group_id = "group_firefox"
    category = "Preferences & Extensions"
    description = "User preferences (prefs.js) and installed extension configurations."
    detection_info = "prefs.js"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        ff_roaming = appdata / "Mozilla" / "Firefox" / "Profiles"
        ff_local = localappdata / "Mozilla" / "Firefox" / "Profiles"
        return ff_roaming.exists() or ff_local.exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        ff_dir = backup_root / "Firefox"
        if ff_dir.exists() and ff_dir.is_dir():
            for p in ff_dir.iterdir():
                if p.is_dir() and ((p / "prefs.js").exists() or (p / "extensions").exists()):
                    return True
        return False

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
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
            log_fn("  -> Saved Firefox extensions data & user profiles configuration.")
            return True
        log_fn("  -> Firefox configuration directories not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        ff_src = backup_root / "Firefox"
        if ff_src.exists():
            safe_terminate_process("firefox.exe", log_fn)
            for prof in ff_src.iterdir():
                target = appdata / "Mozilla" / "Firefox" / "Profiles" / prof.name
                target.mkdir(parents=True, exist_ok=True)
                for f in ["prefs.js", "extensions.json"]:
                    if (prof / f).exists():
                        robust_copy_file(prof / f, target / f)
                for folder in ["extensions", "extension-settings"]:
                    if (prof / folder).exists():
                        robust_copytree(prof / folder, target / folder)
            log_fn("  -> Restored Firefox extension profiles data.")
            return True
        log_fn("  -> Firefox configuration profiles backup not found.")
        return False


# ==========================================
# 7. Microsoft Office (group_office)
# ==========================================

class OfficeRibbonProvider(BaseProvider):
    id = "office_ribbon_qat"
    name = "Ribbon & Quick Access Toolbar (QAT)"
    group_id = "group_office"
    category = "UI Customization"
    description = "Custom ribbon tabs, custom user buttons, and Quick Access Toolbar layouts (*.officeUI, *.qat for Excel, Word, PowerPoint)."
    detection_info = "*.officeUI & *.qat"

    def is_detected(self) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        office_local = localappdata / "Microsoft" / "Office"
        return office_local.exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        return (backup_root / "Office" / "UI").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        office_local = localappdata / "Microsoft" / "Office"
        found = False
        if office_local.exists():
            ui_dest = backup_root / "Office" / "UI"
            for f in office_local.glob("*.officeUI"):
                robust_copy_file(f, ui_dest / f.name)
                found = True
            for f in office_local.glob("*.qat"):
                robust_copy_file(f, ui_dest / f.name)
                found = True
        if found:
            log_fn("  -> Saved Office Ribbon customize UI configuration layout files.")
            return True
        log_fn("  -> Office ribbon customize files not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        ui_src = backup_root / "Office" / "UI"
        if ui_src.exists():
            safe_terminate_process("excel.exe", log_fn)
            safe_terminate_process("winword.exe", log_fn)
            safe_terminate_process("powerpnt.exe", log_fn)
            
            dest = localappdata / "Microsoft" / "Office"
            dest.mkdir(parents=True, exist_ok=True)
            for f in ui_src.iterdir():
                if f.is_file():
                    robust_copy_file(f, dest / f.name)
            log_fn("  -> Restored Office custom layouts.")
            return True
        log_fn("  -> Office UI custom layouts backup not found.")
        return False


class OfficeTemplatesProvider(BaseProvider):
    id = "office_templates_macros"
    name = "Templates, XLSTART & Personal Macros"
    group_id = "group_office"
    category = "Templates & Macros"
    description = "Default templates (Normal.dotm), Excel personal macro startup workbooks (XLSTART/PERSONAL.XLSB), and custom themes."
    detection_info = "Normal.dotm & XLSTART"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        return (appdata / "Microsoft" / "Templates").exists() or (appdata / "Microsoft" / "Excel").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        office_path = backup_root / "Office"
        return (
            (office_path / "Templates").exists()
            or (office_path / "Excel_XLSTART").exists()
            or (office_path / "Word_STARTUP").exists()
        )

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Saved Office core macro & layout templates.")
            return True
        log_fn("  -> Office templates folders not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Restored Office custom macro workbooks & document templates.")
            return True
        log_fn("  -> Office macro templates not found in backup.")
        return False


class OfficeDictionariesProvider(BaseProvider):
    id = "office_dictionaries_signatures"
    name = "Custom Dictionaries & Outlook Signatures"
    group_id = "group_office"
    category = "Preferences & Proofing"
    description = "Custom spelling dictionary files (CUSTOM.DIC in UProof) and saved Outlook email signatures."
    detection_info = "CUSTOM.DIC & Signatures"

    def is_detected(self) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        return (appdata / "Microsoft" / "UProof").exists() or (appdata / "Microsoft" / "Signatures").exists()

    def is_in_backup(self, backup_root: Path) -> bool:
        office_path = backup_root / "Office"
        return (office_path / "UProof").exists() or (office_path / "Signatures").exists()

    def backup(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Saved Custom Dictionaries & Signatures.")
            return True
        log_fn("  -> Office dict/signature folders not found.")
        return False

    def restore(self, backup_root: Path, log_fn: Callable[[str], None]) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
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
            log_fn("  -> Restored Dictionaries & Email Signatures.")
            return True
        log_fn("  -> Signatures or dictionaries not found in backup.")
        return False


# ==========================================
# Self-registration logic
# ==========================================

_PROVIDERS_CLASSES = [
    SystemClockProvider,
    WiFiProvider,
    WingetManifestProvider,
    WallpaperProvider,
    ExplorerSettingsProvider,
    
    SSHKeysProvider,
    GitConfigProvider,
    ShellConfigsProvider,
    
    AntigravityUnsavedProvider,
    AntigravitySettingsProvider,
    AntigravityConfigProvider,
    AntigravityBrainProvider,
    AntigravityCacheProvider,
    
    VSCodeUnsavedProvider,
    VSCodeSettingsProvider,
    VSCodeExtensionsProvider,
    
    NotepadppUnsavedProvider,
    NotepadppConfigProvider,
    
    ChromeBookmarksProvider,
    ChromeExtensionsProvider,
    EdgeBookmarksProvider,
    EdgeExtensionsProvider,
    FirefoxBookmarksProvider,
    FirefoxProfilesProvider,
    
    OfficeRibbonProvider,
    OfficeTemplatesProvider,
    OfficeDictionariesProvider,
]

for cls in _PROVIDERS_CLASSES:
    ProviderRegistry.register(cls())
