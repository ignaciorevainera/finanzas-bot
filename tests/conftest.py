import pytest

@pytest.fixture(autouse=True)
def mock_settings_allowed_chat_id():
    from app.config import settings
    settings.allowed_chat_id = 123

