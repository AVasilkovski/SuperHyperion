"""
SuperHyperion Configuration

Environment configuration for TypeDB, Ollama, and service connections.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TypeDBConfig:
    """TypeDB connection configuration."""
    host: str = os.getenv("TYPEDB_HOST", "localhost")
    port: int = int(os.getenv("TYPEDB_PORT", "1729"))
    database: str = os.getenv("TYPEDB_DATABASE", "superhyperion")
    
    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class OllamaConfig:
    """Ollama LLM configuration."""
    host: str = os.getenv("OLLAMA_HOST", "localhost")
    port: int = int(os.getenv("OLLAMA_PORT", "11434"))
    model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    embedding_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass  
class JupyterConfig:
    """Jupyter sandbox configuration."""
    host: str = os.getenv("JUPYTER_HOST", "localhost")
    port: int = int(os.getenv("JUPYTER_PORT", "8888"))
    token: str = os.getenv("JUPYTER_TOKEN", "superhyperion")
    kernel: str = os.getenv("JUPYTER_KERNEL", "python3")


@dataclass
class APIConfig:
    """FastAPI configuration."""
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = int(os.getenv("API_PORT", "8000"))
    debug: bool = os.getenv("API_DEBUG", "true").lower() == "true"


@dataclass
class Config:
    """Main configuration container."""
    typedb: TypeDBConfig
    ollama: OllamaConfig
    jupyter: JupyterConfig
    api: APIConfig
    
    # Dialectical entropy threshold for triggering Socratic debate
    entropy_threshold: float = float(os.getenv("ENTROPY_THRESHOLD", "0.4"))
    
    # Belief state options
    belief_states: tuple = ("proposed", "verified", "refuted", "debated")
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            typedb=TypeDBConfig(),
            ollama=OllamaConfig(),
            jupyter=JupyterConfig(),
            api=APIConfig(),
        )


# Global config instance
config = Config.from_env()
