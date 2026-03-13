"""
Configuration for Graphiti Studio.
Loads environment variables from the project root .env file.
"""

import os
import shlex
from dotenv import load_dotenv

# Load .env from graphiti-studio/ root (two levels up from app/config.py)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
_env_path = os.path.join(_project_root, ".env")

if os.path.exists(_env_path):
    load_dotenv(_env_path, override=False)
else:
    load_dotenv(override=False)


class Config:
    """Graphiti Studio configuration."""

    # --- Agent runtime ---
    AGENT_RUNTIME: str = os.environ.get("AGENT_RUNTIME", "builtin")
    PI_PROVIDER: str = os.environ.get("PI_PROVIDER", "kimi-coding")
    PI_MODEL: str = os.environ.get("PI_MODEL", "k2p5")
    PI_API_KEY: str = os.environ.get("PI_API_KEY", "")
    PI_AGENT_CLI: str = os.environ.get(
        "PI_AGENT_CLI",
        "npx --yes @mariozechner/pi-coding-agent@latest",
    )

    # --- LLM ---
    LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"))

    # --- Graphiti server ---
    GRAPHITI_BASE_URL: str = os.environ.get("GRAPHITI_BASE_URL", "http://127.0.0.1:8000")
    GRAPHITI_API_KEY: str = os.environ.get("GRAPHITI_API_KEY", "")
    GRAPHITI_SUMMARY_LANGUAGE: str = os.environ.get("GRAPHITI_SUMMARY_LANGUAGE", "original")
    GRAPHITI_TIMEOUT_SECONDS: float = float(os.environ.get("GRAPHITI_TIMEOUT_SECONDS", "900"))
    GRAPHITI_INGEST_TIMEOUT_SECONDS: float = float(os.environ.get("GRAPHITI_INGEST_TIMEOUT_SECONDS", "180"))
    GRAPHITI_TRUST_ENV: bool = os.environ.get("GRAPHITI_TRUST_ENV", "false").lower() == "true"

    # --- Studio ---
    STUDIO_PORT: int = int(os.environ.get("STUDIO_PORT", "5003"))
    STUDIO_DATA_DIR: str = os.environ.get("STUDIO_DATA_DIR", os.path.join(_project_root, "data"))
    PI_SESSION_DIR: str = os.environ.get(
        "PI_SESSION_DIR",
        os.path.join(STUDIO_DATA_DIR, "pi-sessions"),
    )
    PI_EXTENSION_PATH: str = os.environ.get(
        "PI_EXTENSION_PATH",
        os.path.join(_project_root, "pi_extensions", "graphiti_memory.ts"),
    )

    # --- Text processing ---
    DEFAULT_CHUNK_SIZE: int = int(os.environ.get("DEFAULT_CHUNK_SIZE", "1000"))
    DEFAULT_CHUNK_OVERLAP: int = int(os.environ.get("DEFAULT_CHUNK_OVERLAP", "100"))

    # --- Upload limits ---
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50 MB

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of configuration errors (empty means valid)."""
        errors: list[str] = []
        if cls.AGENT_RUNTIME == "pi-rpc":
            if not cls.PI_API_KEY:
                errors.append("PI_API_KEY is not configured")
        elif not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured")
        if not cls.GRAPHITI_API_KEY:
            errors.append("GRAPHITI_API_KEY is not configured")
        return errors

    @classmethod
    def pi_agent_cli_args(cls) -> list[str]:
        """Return the pi-coding-agent launch command as argv."""
        return shlex.split(cls.PI_AGENT_CLI)
