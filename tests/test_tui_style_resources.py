import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from src.tui import app as app_module


def _installed_app_smoke(installed: Path) -> str:
    """构造只使用临时安装包和假配置的无头启动检查。"""
    return f'''
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, {str(installed)!r})
from src.tui import app as app_module

async def verify():
    """从临时安装目录挂载两种引擎并调整终端尺寸。"""
    save = Mock()
    adapter = Mock()
    adapter.list_libraries.return_value = []
    with patch("src.tui.app.load_ui_config", return_value={{}}), \\
         patch("src.tui.app.ZoteroAdapter", return_value=adapter), \\
         patch("src.tui.config_page.load_ui_config", return_value={{}}), \\
         patch("src.tui.config_page.save_ui_config", save), \\
         patch("src.tui.config.save_ui_config", save), \\
         patch("src.tui.config_page.list_llm_profiles", return_value=[]), \\
         patch("src.tui.config_page.list_available_font_families", return_value=[]):
        for engine in ("heavy", "lite"):
            app = app_module.LaTeXTransTuiApp(
                load_history_on_mount=False, initial_engine=engine)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                assert app.query_one("#entry-form").size.width > 0
                await pilot.resize_terminal(40, 30)
                await pilot.pause()
                assert app.query_one("#app-title").size.width > 0
    save.assert_not_called()
    assert Path(app_module.__file__).resolve().is_relative_to(
        Path({str(installed)!r}).resolve())

asyncio.run(verify())
'''


class TuiStyleResourcesTests(unittest.TestCase):
    """验证样式从应用模块旁的资源加载。"""

    def test_stylesheet_is_located_beside_app(self) -> None:
        """保证资源定位与调用方的工作目录无关。"""
        self.assertEqual(app_module.LaTeXTransTuiApp.CSS_PATH, "app.tcss")
        path = Path(app_module.__file__).with_name("app.tcss")
        css = path.read_text(encoding="utf-8")
        self.assertIn("#entry-form", css)
        self.assertIn("#zotero-results", css)

    def test_wheel_has_stylesheet_and_runs_from_temporary_cwd(self) -> None:
        """验证真实 wheel 包含样式且资源定位不依赖启动目录。"""
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "source"
            stage.mkdir()
            shutil.copytree(repository / "src", stage / "src")
            for name in ("setup.py", "main.py", "requirements.txt"):
                shutil.copy2(repository / name, stage / name)
            wheels = root / "wheels"
            built = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", "--no-deps",
                 "--no-build-isolation", "--no-index", "--wheel-dir", str(wheels),
                 str(stage)], cwd=stage, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            wheel = next(wheels.glob("*.whl"))
            installed = root / "installed"
            with zipfile.ZipFile(wheel) as archive:
                self.assertIn("src/tui/app.tcss", archive.namelist())
                archive.extractall(installed)
            foreign_cwd = root / "foreign"
            foreign_cwd.mkdir()
            smoke = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", _installed_app_smoke(installed)],
                cwd=foreign_cwd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stdout + smoke.stderr)


if __name__ == "__main__":
    unittest.main()
