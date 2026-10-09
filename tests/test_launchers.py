import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class LauncherScriptTests(unittest.TestCase):
    """Verify that platform launchers work independently of the caller's cwd."""

    def test_windows_launchers_change_to_project_root(self):
        """Windows launchers should derive and enter the repository root."""
        for name in ("latextrans.cmd", "latextrans-tui.cmd"):
            content = (PROJECT_ROOT / "scripts" / "windows" / name).read_text(encoding="utf-8")

            self.assertIn('cd /d "%~dp0..\\.."', content.lower())
            self.assertIn("call conda activate latextrans", content.lower())
            self.assertNotIn("conda run", content.lower())

    def test_windows_tui_launcher_forwards_all_arguments_to_the_tui(self):
        """The Windows TUI launcher should preserve every caller argument."""
        content = (PROJECT_ROOT / "scripts" / "windows" / "latextrans-tui.cmd").read_text(
            encoding="utf-8"
        )

        self.assertIn('from src.tui.app import run; run()" %*', content)

    def test_linux_launchers_change_to_project_root(self):
        """Linux launchers should derive and enter the repository root."""
        for name in ("latextrans", "latextrans-tui"):
            content = (PROJECT_ROOT / "scripts" / "linux" / name).read_text(encoding="utf-8")

            self.assertIn('cd "$(dirname "$0")/../.."', content)
            self.assertIn('eval "$(conda shell.bash hook)"', content)
            self.assertIn("conda activate latextrans", content)
            self.assertNotIn("conda run", content)

    def test_linux_tui_launcher_forwards_all_arguments_to_the_tui(self):
        """The Linux TUI launcher should preserve every caller argument."""
        content = (PROJECT_ROOT / "scripts" / "linux" / "latextrans-tui").read_text(
            encoding="utf-8"
        )

        self.assertIn('exec latextrans-tui "$@"', content)

    def test_macos_launchers_change_to_project_root(self):
        """macOS launchers should derive and enter the repository root."""
        for name in ("latextrans", "latextrans-tui"):
            content = (PROJECT_ROOT / "scripts" / "macos" / name).read_text(encoding="utf-8")

            self.assertIn('cd "$(dirname "$0")/../.."', content)
            self.assertIn('eval "$(conda shell.bash hook)"', content)
            self.assertIn("conda activate latextrans", content)
            self.assertNotIn("conda run", content)

    def test_macos_tui_launcher_forwards_all_arguments_to_the_tui(self):
        """The macOS TUI launcher should preserve every caller argument."""
        content = (PROJECT_ROOT / "scripts" / "macos" / "latextrans-tui").read_text(
            encoding="utf-8"
        )

        self.assertIn('exec latextrans-tui "$@"', content)


if __name__ == "__main__":
    unittest.main()
