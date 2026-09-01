"""Build and persist the vector store from the source chunks."""
from __future__ import annotations

from engine import config
from engine.vectorstore import VectorStore
from ingest.chunker import build_chunks


def main() -> None:
    config.ensure_dirs()
    chunks = build_chunks()
    store = VectorStore()
    store.add(
        ids=[c["chunk_id"] for c in chunks],
        texts=[c["text"] for c in chunks],
        metas=[{k: c[k] for k in ("source_id", "source_type", "service", "entity_ids", "text")}
               for c in chunks],
    )
    store.save(config.VECTOR_STORE_FILE, config.VECTOR_META_FILE)
    print(f"[build_vectors] indexed {len(store)} chunks "
          f"(embedder: {store and 'ok'}) -> {config.VECTOR_STORE_FILE.name}")


if __name__ == "__main__":
    main()
