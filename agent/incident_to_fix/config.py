"""Settings for the incident_to_fix agent. Env vars (Secret Manager on Cloud Run, `.env` locally)."""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=False)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FIX_MODEL = os.environ.get("GEMINI_FIX_MODEL", "gemini-2.5-pro")

# The allow-list lives in code (specs/03-guardrails.md) so config cannot widen it.
ALLOWED_OWNER = "alokranjan04"
ALLOWED_REPO_NAME = "incident-to-fix-demo"
ALLOWED_REPO = f"{ALLOWED_OWNER}/{ALLOWED_REPO_NAME}"

ALLOWED_REPO_URL = f"https://github.com/{ALLOWED_REPO}.git"

DEFECT_CATEGORY = "software_defect"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"

# Guardrail limits (specs/03-guardrails.md).
MAX_FILES_PER_PR = 3
TOOL_CALL_BUDGET = 40
MAX_FIX_ATTEMPTS = 2
FIX_BRANCH_PREFIX = "fix/"
