"""
Ollama LLM Integration

Provides LLM and embedding functions using Ollama.
"""

from typing import Optional, List
import httpx
from dataclasses import dataclass

from src.config import config


@dataclass
class LLMResponse:
    """Response from LLM generation."""
    content: str
    model: str
    total_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None


class OllamaClient:
    """Client for Ollama LLM inference."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        self.base_url = base_url or config.ollama.base_url
        self.model = model or config.ollama.model
        self.embedding_model = embedding_model or config.ollama.embedding_model
        self._client = httpx.Client(timeout=120.0)
    
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate text from prompt."""
        model = model or self.model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        
        if system:
            payload["system"] = system
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        response = self._client.post(
            f"{self.base_url}/api/generate",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        
        return LLMResponse(
            content=data["response"],
            model=data["model"],
            total_duration=data.get("total_duration"),
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
        )
    
    def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Chat completion with message history."""
        model = model or self.model
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        
        response = self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        
        return LLMResponse(
            content=data["message"]["content"],
            model=data["model"],
            total_duration=data.get("total_duration"),
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
        )
    
    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """Generate embedding for text."""
        model = model or self.embedding_model
        
        response = self._client.post(
            f"{self.base_url}/api/embed",
            json={"model": model, "input": text},
        )
        response.raise_for_status()
        data = response.json()
        
        return data["embeddings"][0]
    
    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        model = model or self.embedding_model
        
        response = self._client.post(
            f"{self.base_url}/api/embed",
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        
        return data["embeddings"]
    
    def list_models(self) -> List[str]:
        """List available models."""
        response = self._client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m["name"] for m in data.get("models", [])]
    
    def pull_model(self, model: str):
        """Pull a model from Ollama registry."""
        response = self._client.post(
            f"{self.base_url}/api/pull",
            json={"name": model, "stream": False},
            timeout=600.0,  # Models can take a while to download
        )
        response.raise_for_status()
        return response.json()
    
    def close(self):
        """Close the HTTP client."""
        self._client.close()


# Global client instance
ollama = OllamaClient()


def ensure_model(model: Optional[str] = None):
    """Ensure a model is available, pulling if necessary."""
    model = model or config.ollama.model
    available = ollama.list_models()
    
    if model not in available:
        print(f"Pulling model: {model}")
        ollama.pull_model(model)
        print(f"Model ready: {model}")
    else:
        print(f"Model already available: {model}")


if __name__ == "__main__":
    # Test connection
    models = ollama.list_models()
    print(f"Available models: {models}")
    
    # Test generation
    response = ollama.generate("Hello! What is 2+2?")
    print(f"Response: {response.content}")
