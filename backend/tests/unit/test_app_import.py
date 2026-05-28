from app.main import app


def test_app_imports() -> None:
    assert app.title == "PatchDIFF MVP"


def test_health_routes_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/health/live" in paths
    assert "/health/ready" in paths

