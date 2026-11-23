"""Test setup. Placeholder secrets and settings are set before any module loads `.env`
(load_dotenv never overrides), so tests never see real credentials. Importing
agent.incident_to_fix builds the toolsets; they connect lazily, so nothing goes online."""
import os

import pytest

TEST_PASSWORD = "test-password-not-real"
TEST_TOKEN = "test-token-not-real"
TEST_MODEL = "test-model-not-real"

os.environ["SNOW_INSTANCE_URL"] = "https://example.service-now.com"
os.environ["SNOW_USER"] = "mcp.integration"
os.environ["SNOW_PASSWORD"] = TEST_PASSWORD
os.environ["GITHUB_TOKEN"] = TEST_TOKEN
os.environ["GEMINI_MODEL"] = TEST_MODEL
os.environ["GEMINI_FIX_MODEL"] = ""  # empty: falls back to GEMINI_MODEL


@pytest.fixture
def test_password() -> str:
    return TEST_PASSWORD


@pytest.fixture
def test_token() -> str:
    return TEST_TOKEN
