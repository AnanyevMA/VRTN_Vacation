import sys
import os
import pytest

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.api.chat_routes import clear_rate_limits


@pytest.fixture(autouse=True)
def auto_reset_rate_limits():
    clear_rate_limits()
    yield
    clear_rate_limits()
