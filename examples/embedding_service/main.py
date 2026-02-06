#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from fastapi import FastAPI
from pydantic import BaseModel
from gunicorn.dirty.client import get_dirty_client

app = FastAPI()


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    client = get_dirty_client()
    result = client.execute(
        "embedding_service.embedding_app:EmbeddingApp",
        "embed",
        request.texts
    )
    return EmbedResponse(embeddings=result)


@app.get("/health")
async def health():
    return {"status": "ok"}
