import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityStaticTest(unittest.TestCase):
    def test_adapter_has_no_subprocess_or_shell_calls(self):
        adapter = ROOT / "checkmk" / "notifications" / "telegram_plus_notify_listener"
        text = adapter.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", text)
        self.assertNotIn("shell=True", text)
        self.assertIn("socket.AF_UNIX", text)
        self.assertIn("settimeout", text)

    def test_telegram_bot_does_not_use_shell_true(self):
        text = (ROOT / "resources" / "telegram_bot.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", text)

    def test_installer_does_not_install_dependencies_into_checkmk_site(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("pip3 install --target", text)
        self.assertNotIn("rm -rf \"$telegram_plus_dir\"/httpx", text)
        self.assertIn("/opt/checkmk-telegram-plus", text)
        self.assertIn("/etc/checkmk-telegram-plus", text)
        self.assertIn("config.ini.bak.", text)


if __name__ == "__main__":
    unittest.main()

