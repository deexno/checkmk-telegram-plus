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

    def test_installer_reviews_existing_config_without_printing_secrets(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("Configuration review for", text)
        self.assertIn("Secrets are never printed", text)
        self.assertIn("press Enter to keep", text)
        self.assertIn("Configure optional Checkmk Web graph export settings now?", text)
        self.assertIn("Telegram API token", text)
        self.assertIn("Bot password", text)

    def test_httpx_is_pinned_for_openai_compatibility(self):
        text = (ROOT / "resources" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("httpx<0.28", text)

    def test_graphs_have_web_export_fallback(self):
        bridge = (ROOT / "checkmk" / "bridge" / "checkmk_bridge.py").read_text(
            encoding="utf-8"
        )
        config = (ROOT / "resources" / "config.ini").read_text(encoding="utf-8")
        self.assertIn("fetch_graphs_from_web", bridge)
        self.assertIn("fetch_graphs_from_ajax", bridge)
        self.assertIn("ajax_graph_images.py", bridge)
        self.assertIn("graph_image.py", bridge)
        self.assertIn("graph_fetch_attempts", bridge)
        self.assertIn("should_retry_graph_fetch", bridge)
        self.assertIn("SSLCertVerificationError", bridge)
        self.assertIn("_create_unverified_context", bridge)
        self.assertIn("is_loopback_host", bridge)
        self.assertIn("Authorization", bridge)
        self.assertIn("allow_legacy_url_auth", bridge)
        self.assertIn("[checkmk_web]", config)
        self.assertIn("automation_secret", config)
        self.assertIn("allow_legacy_url_auth = no", config)

    def test_bridge_client_timeout_allows_slow_agent_checks(self):
        text = (
            ROOT / "src" / "checkmk_telegram_plus" / "checkmk" / "client.py"
        ).read_text(encoding="utf-8")
        self.assertIn("timeout: float = 90.0", text)
        self.assertIn("message = f\"{message}: {error}\"", text)

    def test_app_service_runs_as_external_user(self):
        text = (
            ROOT / "resources" / "checkmk-telegram-plus.service"
        ).read_text(encoding="utf-8")
        self.assertIn("PermissionsStartOnly=true", text)
        self.assertIn("ExecStartPre=+/bin/chown root:<app_user>", text)
        self.assertIn("ExecStartPre=+/bin/chmod 2770 <run_dir>", text)
        self.assertIn("User=<app_user>", text)
        self.assertIn("Environment=PYTHONPATH=<pythonpath>", text)

    def test_bot_has_no_direct_checkmk_import_or_command_execution(self):
        text = (ROOT / "resources" / "telegram_bot.py").read_text(encoding="utf-8")
        self.assertNotIn("import livestatus", text)
        self.assertNotIn("cmk.notification_plugins", text)
        self.assertNotIn("subprocess.run", text)
        self.assertIn("CheckmkBridgeClient", text)
        self.assertIn("def is_user_admin", text)
        self.assertIn("reject_non_admin", text)

    def test_bridge_service_runs_as_site_user(self):
        text = (
            ROOT / "resources" / "checkmk-telegram-plus-bridge.service"
        ).read_text(encoding="utf-8")
        self.assertIn("<site_python> <bridge_script>", text)
        self.assertIn("<runuser_path> -l <omd_site>", text)


if __name__ == "__main__":
    unittest.main()
