import os
import requests
import numpy as np


def test_embedding_endpoint():
    base_url = os.environ.get("EMBEDDING_SERVICE_URL", "http://127.0.0.1:8000")
    url = f"{base_url}/embed"

    # Test single text
    response = requests.post(url, json={"texts": ["Hello world"]})
    assert response.status_code == 200
    data = response.json()
    assert len(data["embeddings"]) == 1
    assert len(data["embeddings"][0]) == 384  # MiniLM dimension

    # Test batch
    texts = ["First sentence", "Second sentence", "Third one"]
    response = requests.post(url, json={"texts": texts})
    assert response.status_code == 200
    data = response.json()
    assert len(data["embeddings"]) == 3

    # Test similarity (same text = same embedding)
    response = requests.post(url, json={"texts": ["test", "test"]})
    emb1, emb2 = response.json()["embeddings"]
    assert np.allclose(emb1, emb2, rtol=1e-5, atol=1e-6)

    print("All tests passed!")


if __name__ == "__main__":
    test_embedding_endpoint()
