from gunicorn.dirty.app import DirtyApp


class EmbeddingApp(DirtyApp):
    def init(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

    def embed(self, texts):
        embeddings = self.model.encode(texts)
        return embeddings.tolist()

    def close(self):
        del self.model
