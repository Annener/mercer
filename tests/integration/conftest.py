"""
pytest config for integration tests.
"""
import pytest

# pytest-asyncio: все тесты в этой директории используют asyncio
def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("asyncio") is None:
            item.add_marker(pytest.mark.asyncio)
