"""API服务器模块"""

__all__ = ["create_app"]


def __getattr__(name):
    if name == "create_app":
        from api_server.main import create_app

        return create_app
    raise AttributeError(name)
