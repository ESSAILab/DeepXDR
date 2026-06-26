import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ai_agent" / "defense" / "mcp_server.py"


@pytest.fixture()
def mcp_server_module():
    spec = importlib.util.spec_from_file_location("mcp_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_block_ip_rejects_nginx_config_injection(tmp_path, mcp_server_module):
    block_file = tmp_path / "blocked_ips.conf"
    block_file.write_text("203.0.113.1 1;\n")
    calls = []

    security_tools = mcp_server_module.SecurityTools
    security_tools._blocked_ips_file = str(block_file)
    security_tools._run_nginx_command = staticmethod(lambda args: calls.append(args))

    result = security_tools.block_ip_port("198.51.100.9 1;\n0.0.0.0/0", "all")

    assert result["status"] == "error"
    assert block_file.read_text() == "203.0.113.1 1;\n"
    assert calls == []


def test_block_ip_tests_nginx_and_rolls_back_on_failure(tmp_path, mcp_server_module):
    block_file = tmp_path / "blocked_ips.conf"
    original_content = "203.0.113.2 1;\n"
    block_file.write_text(original_content)

    security_tools = mcp_server_module.SecurityTools
    security_tools._blocked_ips_file = str(block_file)

    def fail_nginx_test(args):
        if args == ["nginx", "-t"]:
            raise RuntimeError("nginx config test failed")

    security_tools._run_nginx_command = staticmethod(fail_nginx_test)

    result = security_tools.block_ip_port("198.51.100.11", "all")

    assert result["status"] == "error"
    assert block_file.read_text() == original_content


@pytest.mark.parametrize(
    "blocked_ip", ["0.0.0.0/0", "::/0", "198.51.0.0/16", "2001:db8::/63"]
)
def test_block_ip_rejects_overly_broad_cidr_ranges(tmp_path, mcp_server_module, blocked_ip):
    block_file = tmp_path / "blocked_ips.conf"
    original_content = "203.0.113.1 1;\n"
    block_file.write_text(original_content)
    calls = []

    security_tools = mcp_server_module.SecurityTools
    security_tools._blocked_ips_file = str(block_file)
    security_tools._run_nginx_command = staticmethod(lambda args: calls.append(args))

    result = security_tools.block_ip_port(blocked_ip, "all")

    assert result["status"] == "error"
    assert block_file.read_text() == original_content
    assert calls == []


def test_block_ip_rejects_host_bits_in_cidr(tmp_path, mcp_server_module):
    block_file = tmp_path / "blocked_ips.conf"
    original_content = "203.0.113.1 1;\n"
    block_file.write_text(original_content)
    calls = []

    security_tools = mcp_server_module.SecurityTools
    security_tools._blocked_ips_file = str(block_file)
    security_tools._run_nginx_command = staticmethod(lambda args: calls.append(args))

    result = security_tools.block_ip_port("198.51.100.129/25", "all")

    assert result["status"] == "error"
    assert block_file.read_text() == original_content
    assert calls == []


def test_block_ip_accepts_valid_cidr_and_reloads_after_test(tmp_path, mcp_server_module):
    block_file = tmp_path / "blocked_ips.conf"
    block_file.write_text("")
    calls = []

    security_tools = mcp_server_module.SecurityTools
    security_tools._blocked_ips_file = str(block_file)
    security_tools._run_nginx_command = staticmethod(lambda args: calls.append(args))

    result = security_tools.block_ip_port("198.51.100.128/25", "all")

    assert result["status"] == "success"
    assert result["ip"] == "198.51.100.128/25"
    assert block_file.read_text() == "198.51.100.128/25 1;\n"
    assert calls == [["nginx", "-t"], ["nginx", "-s", "reload"]]
