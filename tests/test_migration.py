"""
Automated unit and integration test suite for Laptop Migration Hub.
Tests API endpoints, Chrome/Edge extension backup (including uBlock Origin Lite),
folder creation, and directory navigation.

Made with ❤️ in 🇳🇵 by Alok - hello@aloks.com.np
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import (
    get_system_info,
    browse_directory,
    create_directory,
    inspect_backup,
    index,
    MkdirRequest,
)
from migrator.providers import (
    ChromeExtensionsProvider,
    EdgeExtensionsProvider,
)


class TestLaptopMigrator(unittest.TestCase):
    def setUp(self):
        os.environ["MIGRATOR_TESTING"] = "1"
        self.test_dir = Path(tempfile.mkdtemp(prefix="migrator_test_"))

    def tearDown(self):
        os.environ.pop("MIGRATOR_TESTING", None)
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_index_html_features(self):
        """Verify index HTML contains feature search, selected only toggle, and new folder creation elements."""
        html_response = index()
        html = html_response if isinstance(html_response, str) else html_response.body.decode("utf-8")
        self.assertIn('id="featureSearchInput"', html)
        self.assertIn('id="btnShowSelectedOnly"', html)
        self.assertIn('promptCreateNewFolder()', html)
        self.assertIn('toggleNewFolderInput', html)
        self.assertIn('newFolderInlineBar', html)
        self.assertIn('applyFeatureFilters()', html)

    def test_get_system_info(self):
        """Verify get_system_info returns expected data structure and groups."""
        info = get_system_info()
        self.assertIsNotNone(info.default_backup_path)
        self.assertIsInstance(info.is_admin, bool)
        self.assertGreater(len(info.groups), 0)

        # Check that Chrome and other expected software groups are registered
        group_ids = [g.id for g in info.groups]
        self.assertIn("group_chrome", group_ids)

        # Verify each group has sub_items with necessary fields
        for g in info.groups:
            self.assertIsNotNone(g.name)
            self.assertIsInstance(g.sub_items, list)
            for item in g.sub_items:
                self.assertIsNotNone(item.id)
                self.assertIsNotNone(item.name)

    def test_create_directory_and_browse(self):
        """Verify creating a new folder via create_directory and navigating it via browse_directory."""
        new_folder_path = self.test_dir / "Subfolder_A" / "Nested_Folder"
        req = MkdirRequest(path=str(new_folder_path))
        res = create_directory(req)
        
        self.assertEqual(res["status"], "created")
        self.assertTrue(new_folder_path.exists())
        self.assertTrue(new_folder_path.is_dir())

        # Test browsing the created parent directory
        browse_res = browse_directory(str(self.test_dir / "Subfolder_A"))
        self.assertIn("Nested_Folder", browse_res.folders)

    def test_inspect_backup_directory(self):
        """Verify inspecting an empty directory versus a simulated backup directory."""
        # Empty folder should not be recognized as a valid backup
        empty_res = inspect_backup(str(self.test_dir))
        self.assertFalse(empty_res.is_backup)
        self.assertEqual(empty_res.item_count, 0)

        # Create a mock backup structure
        chrome_backup = self.test_dir / "Chrome" / "Default" / "Preferences"
        chrome_backup.parent.mkdir(parents=True, exist_ok=True)
        chrome_backup.write_text("{}", encoding="utf-8")

        inspect_res = inspect_backup(str(self.test_dir))
        self.assertTrue(inspect_res.is_backup)
        self.assertIn("chrome_extensions", inspect_res.found_sub_items)

    @patch("migrator.providers.subprocess.run")
    def test_chrome_ublock_origin_lite_backup_and_restore(self, mock_subproc):
        """
        Verify that ChromeExtensionsProvider successfully backs up and restores
        uBlock Origin Lite data (Local Extension Settings with ID ddkjiahejlhfcafbddmgiahcphecmpfh,
        Preferences, DNR Extension Rules, etc.).
        """
        mock_localappdata = self.test_dir / "LocalAppData"
        old_localappdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(mock_localappdata)

        try:
            # 1. Simulate Chrome User Data with uBlock Origin Lite
            ubol_id = "ddkjiahejlhfcafbddmgiahcphecmpfh"
            chrome_profile = mock_localappdata / "Google" / "Chrome" / "User Data" / "Default"
            ubol_storage = chrome_profile / "Local Extension Settings" / ubol_id
            ubol_storage.mkdir(parents=True, exist_ok=True)
            
            # Create dummy LevelDB files representing uBOL custom filters & settings
            (ubol_storage / "CURRENT").write_text("CURRENT", encoding="utf-8")
            (ubol_storage / "000003.log").write_text("ubol_custom_filters_data", encoding="utf-8")
            (chrome_profile / "Preferences").write_text('{"extensions":{"settings":{}}}', encoding="utf-8")

            # Also create DNR Extension Rules
            dnr_rules = chrome_profile / "DNR Extension Rules" / ubol_id
            dnr_rules.mkdir(parents=True, exist_ok=True)
            (dnr_rules / "rules.json").write_text('[]', encoding="utf-8")

            provider = ChromeExtensionsProvider()
            self.assertTrue(provider.is_detected())

            # 2. Perform Backup
            backup_root = self.test_dir / "BackupDestination"
            logs = []
            backed_up = provider.backup(backup_root, log_fn=logs.append)
            self.assertTrue(backed_up)

            # Verify uBlock Origin Lite files exist in backup
            backed_ubol = backup_root / "Chrome" / "Default" / "Local Extension Settings" / ubol_id
            self.assertTrue(backed_ubol.exists())
            self.assertTrue((backed_ubol / "000003.log").exists())
            self.assertEqual((backed_ubol / "000003.log").read_text(encoding="utf-8"), "ubol_custom_filters_data")
            self.assertTrue((backup_root / "Chrome" / "Default" / "Preferences").exists())
            self.assertTrue((backup_root / "Chrome" / "Default" / "DNR Extension Rules" / ubol_id).exists())

            # 3. Simulate a fresh machine (remove Chrome user data)
            shutil.rmtree(mock_localappdata / "Google" / "Chrome" / "User Data")
            self.assertFalse((chrome_profile / "Local Extension Settings" / ubol_id).exists())

            # 4. Perform Restore
            restore_logs = []
            restored = provider.restore(backup_root, log_fn=restore_logs.append)
            self.assertTrue(restored)

            # Verify uBlock Origin Lite files are fully restored
            restored_ubol_file = chrome_profile / "Local Extension Settings" / ubol_id / "000003.log"
            self.assertTrue(restored_ubol_file.exists())
            self.assertEqual(restored_ubol_file.read_text(encoding="utf-8"), "ubol_custom_filters_data")
            self.assertTrue((chrome_profile / "Preferences").exists())
            self.assertTrue((chrome_profile / "DNR Extension Rules" / ubol_id / "rules.json").exists())

        finally:
            if old_localappdata:
                os.environ["LOCALAPPDATA"] = old_localappdata


if __name__ == "__main__":
    unittest.main()
