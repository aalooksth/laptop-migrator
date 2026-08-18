import json
import subprocess
import winreg
from pathlib import Path
from typing import Any, Callable, Dict, Optional

def export_registry_key_tree(root: int, subkey_path: str) -> Optional[Dict[str, Any]]:
    """Recursively export a registry key hierarchy and its values to a serializable dict."""
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
    """Recursively write values and subkeys from a dict into the Windows Registry."""
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
        # Write values
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

        # Recursively create subkeys
        for child_name, child_data in data.get("subkeys", {}).items():
            import_registry_key_tree(root, f"{subkey_path}\\{child_name}", child_data, log_fn)

        return True
    finally:
        winreg.CloseKey(key)

def backup_clock_and_regional(backup_dir: Path, log_fn: Callable[[str], None]):
    """Export multi-timezone clocks, international locale formatting, and timezone info."""
    sys_dest = backup_dir / "System"
    sys_dest.mkdir(parents=True, exist_ok=True)

    # 1. Multi-timezone Additional Clocks (HKCU\Control Panel\TimeDate)
    log_fn("Exporting Multi-Timezone Additional Clocks from HKCU\\Control Panel\\TimeDate...")
    timedate_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\TimeDate")
    if timedate_data:
        clocks_file = sys_dest / "Clock_TimeDate.json"
        with open(clocks_file, "w", encoding="utf-8") as f:
            json.dump(timedate_data, f, indent=2)
        
        # Log detected additional clocks
        add_clocks = timedate_data.get("subkeys", {}).get("AdditionalClocks", {}).get("subkeys", {})
        clock_summaries = []
        for cid, cinfo in add_clocks.items():
            vals = cinfo.get("values", {})
            enabled = vals.get("Enable", {}).get("val") == 1
            tz_name = vals.get("TzRegKeyName", {}).get("val", "Unknown TZ")
            disp_name = vals.get("DisplayName", {}).get("val", f"Clock {cid}")
            status = "Enabled" if enabled else "Disabled"
            clock_summaries.append(f"Clock {cid}: '{disp_name}' ({tz_name}, {status})")
        if clock_summaries:
            log_fn(f"  -> Found {len(clock_summaries)} additional clock(s): {', '.join(clock_summaries)}")
        else:
            log_fn("  -> TimeDate exported (no active additional clocks configured).")
    else:
        log_fn("  -> No custom TimeDate settings found in HKCU.")

    # 2. International & Regional Formats (HKCU\Control Panel\International)
    log_fn("Exporting Regional & Locale formatting from HKCU\\Control Panel\\International...")
    intl_data = export_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\International")
    if intl_data:
        intl_file = sys_dest / "Clock_International.json"
        with open(intl_file, "w", encoding="utf-8") as f:
            json.dump(intl_data, f, indent=2)
        locale_name = intl_data.get("values", {}).get("LocaleName", {}).get("val", "Default")
        log_fn(f"  -> International locale settings exported (Locale: {locale_name}).")

    # 3. System TimeZone Information (HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation)
    log_fn("Exporting System TimeZone information...")
    tz_data = export_registry_key_tree(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
    if tz_data:
        tz_file = sys_dest / "Clock_TimeZone.json"
        with open(tz_file, "w", encoding="utf-8") as f:
            json.dump(tz_data, f, indent=2)
        tz_name = tz_data.get("values", {}).get("TimeZoneKeyName", {}).get("val", "Unknown")
        log_fn(f"  -> System Timezone exported ({tz_name}).")

def restore_clock_and_regional(backup_dir: Path, log_fn: Callable[[str], None]):
    """Restore multi-timezone clocks, international locale formatting, and timezone info."""
    sys_src = backup_dir / "System"
    if not sys_src.exists():
        log_fn("System backup directory not found.")
        return

    # 1. Multi-timezone Additional Clocks
    clocks_file = sys_src / "Clock_TimeDate.json"
    if clocks_file.exists():
        log_fn("Restoring Multi-Timezone Additional Clocks to HKCU\\Control Panel\\TimeDate...")
        try:
            with open(clocks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\TimeDate", data, log_fn):
                log_fn("  -> Additional clocks successfully restored to HKCU.")
        except Exception as e:
            log_fn(f"  -> Error restoring Additional Clocks: {e}")

    # 2. International & Regional Formats
    intl_file = sys_src / "Clock_International.json"
    if intl_file.exists():
        log_fn("Restoring Regional & Locale formatting to HKCU\\Control Panel\\International...")
        try:
            with open(intl_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if import_registry_key_tree(winreg.HKEY_CURRENT_USER, r"Control Panel\International", data, log_fn):
                log_fn("  -> International locale settings successfully restored.")
        except Exception as e:
            log_fn(f"  -> Error restoring International settings: {e}")

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
                    log_fn(f"  -> Note: tzutil exited with code {res.returncode}. (Setting system timezone requires admin/elevation)")
        except Exception as e:
            log_fn(f"  -> Error setting TimeZone: {e}")
