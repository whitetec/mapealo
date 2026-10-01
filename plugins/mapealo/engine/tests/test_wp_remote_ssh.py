import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from tests._fx import write_app  # asegura sys.path
from analyzer.wp_remote.ssh import run_wp_cli, _build_ssh_cmd, WPRemoteError


CFG_OK = {"ssh": {
    "host": "1.2.3.4", "user": "deploy", "key": "~/.ssh/key",
    "wp_path": "/var/www/site/",
}}


class TestBuildSshCmd(unittest.TestCase):
    def test_basic_command(self):
        argv = _build_ssh_cmd(CFG_OK["ssh"], ["plugin", "list", "--format=json"])
        self.assertEqual(argv[0], "ssh")
        self.assertIn("-i", argv)
        self.assertIn("deploy@1.2.3.4", argv)
        # remote command es el último arg, una sola string
        self.assertIn("wp", argv[-1])
        self.assertIn("--path=/var/www/site/", argv[-1])
        self.assertIn("plugin", argv[-1])

    def test_port_added_when_present(self):
        cfg = {"host": "x", "user": "y", "wp_path": "/p", "port": 2222}
        argv = _build_ssh_cmd(cfg, ["foo"])
        self.assertIn("-p", argv)
        self.assertIn("2222", argv)

    def test_missing_required_raises(self):
        with self.assertRaises(WPRemoteError):
            _build_ssh_cmd({"host": "x", "user": "y"}, ["foo"])  # falta wp_path

    def test_quotes_args_with_spaces(self):
        argv = _build_ssh_cmd(CFG_OK["ssh"], ["post", "list", "--post_type=my type"])
        # El último arg debe tener el valor escapado
        self.assertIn("my type", argv[-1])


def _mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    p = MagicMock(spec=subprocess.CompletedProcess)
    p.stdout, p.stderr, p.returncode = stdout, stderr, returncode
    return p


class TestRunWpCli(unittest.TestCase):
    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_parses_json(self, mock_run):
        mock_run.return_value = _mock_proc(stdout='[{"name":"akismet","status":"active"}]')
        result = run_wp_cli(CFG_OK, ["plugin", "list"])
        self.assertEqual(result, [{"name": "akismet", "status": "active"}])
        # Confirmar que se agregó --format=json
        call_argv = mock_run.call_args[0][0]
        self.assertIn("--format=json", call_argv[-1])

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_raw_when_parse_json_false(self, mock_run):
        mock_run.return_value = _mock_proc(stdout="raw text")
        out = run_wp_cli(CFG_OK, ["cli", "version"], parse_json=False)
        self.assertEqual(out, "raw text")
        call_argv = mock_run.call_args[0][0]
        self.assertNotIn("--format=json", call_argv[-1])

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run):
        mock_run.return_value = _mock_proc(stderr="permission denied", returncode=1)
        with self.assertRaises(WPRemoteError) as ctx:
            run_wp_cli(CFG_OK, ["plugin", "list"])
        self.assertIn("permission denied", str(ctx.exception))

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_invalid_json_raises(self, mock_run):
        mock_run.return_value = _mock_proc(stdout="not json")
        with self.assertRaises(WPRemoteError) as ctx:
            run_wp_cli(CFG_OK, ["plugin", "list"])
        self.assertIn("JSON inválido", str(ctx.exception))

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_timeout_raises(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=5)
        with self.assertRaises(WPRemoteError) as ctx:
            run_wp_cli(CFG_OK, ["plugin", "list"], timeout=5)
        self.assertIn("timeout", str(ctx.exception).lower())

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_ssh_not_found_raises(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with self.assertRaises(WPRemoteError):
            run_wp_cli(CFG_OK, ["plugin", "list"])

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_empty_stdout_returns_empty_list(self, mock_run):
        mock_run.return_value = _mock_proc(stdout="")
        result = run_wp_cli(CFG_OK, ["plugin", "list"])
        self.assertEqual(result, [])

    @patch("analyzer.wp_remote.ssh.subprocess.run")
    def test_wp_extra_args_appended(self, mock_run):
        mock_run.return_value = _mock_proc(stdout="[]")
        cfg = {**CFG_OK, "wp_extra_args": ["--skip-plugins=insert-headers-and-footers"]}
        run_wp_cli(cfg, ["plugin", "list"])
        remote_cmd = mock_run.call_args[0][0][-1]
        self.assertIn("--skip-plugins=insert-headers-and-footers", remote_cmd)


if __name__ == "__main__":
    unittest.main()
