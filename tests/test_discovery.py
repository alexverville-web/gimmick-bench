import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gimmick_bench.apps import discovery


class FakePlatform:
    def __init__(self, root, versions):
        self.root = root
        self.versions = versions

    def default_app_roots(self):
        return [self.root]

    def app_version(self, path):
        for key, v in self.versions.items():
            if key in str(path):
                return v
        return None


def touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


class WindowsLayoutTest(unittest.TestCase):
    """Uses the Windows folder layout (the module's non-macOS branch)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for year in ("2024", "2025", "2026"):
            sf = self.tmp / "Adobe" / f"Adobe After Effects {year}" / "Support Files"
            touch(sf / "AfterFX.exe")
            touch(sf / "aerender.exe")
        for year in ("2023", "2024", "2027"):
            root = self.tmp / f"Maxon Cinema 4D {year}"
            touch(root / "Cinema 4D.exe")
            touch(root / "c4dpy.exe")
            touch(root / "Commandline.exe")
        (self.tmp / "Maxon Cinema 4D 2024" / "plugins" / "c4doctane").mkdir(parents=True)
        self.platform = FakePlatform(self.tmp, {
            "Effects 2024": "24.6.0", "Effects 2025": "25.6.0", "Effects 2026": "26.5.0",
            "4D 2023": "2023.2.2", "4D 2024": "2024.5.1", "4D 2027": "2027.0.0",
        })

    def test_after_effects(self):
        with mock.patch.object(discovery, "IS_MAC", False):
            found = discovery.find_after_effects(self.platform)
        self.assertEqual([i.year for i in found], ["2026", "2025", "2024"])
        old = found[-1]
        self.assertFalse(old.supported)
        self.assertIn("older", old.note)
        self.assertEqual(discovery.pick(found).version, "26.5.0")
        self.assertEqual(discovery.pick(found, "2025").version, "25.6.0")
        self.assertIsNone(discovery.pick(found, "2024"))

    def test_cinema4d_and_octane_folder(self):
        with mock.patch.object(discovery, "IS_MAC", False):
            found = discovery.find_cinema4d(self.platform)
        self.assertEqual(discovery.pick(found).version, "2027.0.0")
        c24 = discovery.pick(found, "2024")
        self.assertTrue(c24.octane_candidates)
        self.assertFalse([i for i in found if i.year == "2023"][0].supported)


if __name__ == "__main__":
    unittest.main()
