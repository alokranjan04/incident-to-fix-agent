"""Test setup: importing agent.incident_to_fix builds the toolsets, which need a token.
They connect lazily, so a dummy value keeps tests offline and away from the real secret."""
import os

os.environ["GITHUB_TOKEN"] = "test-token-not-real"
