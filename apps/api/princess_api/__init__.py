"""Product API entry point (FastAPI composition)."""
from .app import Services, create_app

__all__ = ["Services", "create_app"]
