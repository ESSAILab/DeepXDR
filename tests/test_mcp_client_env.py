import importlib
import sys
import types


def import_mcp_client(monkeypatch):
    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = object
    mcp_module.StdioServerParameters = object

    mcp_client_module = types.ModuleType("mcp.client")
    mcp_stdio_module = types.ModuleType("mcp.client.stdio")
    mcp_stdio_module.stdio_client = lambda *_args, **_kwargs: None

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_stdio_module)
    monkeypatch.syspath_prepend("ai_agent")

    sys.modules.pop("mitre_attck_agent.mcp_client", None)
    return importlib.import_module("mitre_attck_agent.mcp_client")


def test_mitre_mcp_env_excludes_service_secrets(monkeypatch):
    monkeypatch.setenv("MITRE_MCP_DATA_DIR", "/tmp/mitre-data")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@db/prod")
    monkeypatch.setenv("REDIS_URL", "redis://:redispass@cache:6379/0")

    mcp_client = import_mcp_client(monkeypatch)

    assert mcp_client._build_mitre_mcp_env() == {"MITRE_MCP_DATA_DIR": "/tmp/mitre-data"}


def test_mitre_mcp_env_uses_safe_default(monkeypatch):
    monkeypatch.delenv("MITRE_MCP_DATA_DIR", raising=False)

    mcp_client = import_mcp_client(monkeypatch)

    assert mcp_client._build_mitre_mcp_env() == {"MITRE_MCP_DATA_DIR": "/app/ai_agent/data"}
