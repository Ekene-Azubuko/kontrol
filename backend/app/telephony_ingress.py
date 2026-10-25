"""Public phone ingress: signed callbacks/media only, never dispatcher credentials or private call APIs."""

from fastapi import FastAPI

from .live_media import router as media_router
from .telephony_api import provider_router

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(provider_router)
app.include_router(media_router)


@app.get("/health")
def health():
    """Expose process readiness without publishing dispatcher data or provider configuration."""
    return {"status": "ok"}
