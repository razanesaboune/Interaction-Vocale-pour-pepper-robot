"""
Étape 3 – Indexation des chunks dans ChromaDB.

Entrée : data/kb/chunks.json (produit par rag_chunking.py)
Sortie : data/chroma_db/  (collection « esiee_it_kb », distance cosinus)

Les vecteurs sont calculés par Ollama avec le modèle embeddinggemma.
embeddinggemma attend un préfixe : « title: … | text: … » pour les
documents et « task: question answering | query: … » pour les questions.
"""

import json
import time

import chromadb
import requests

from rag_commun import CHROMA_DIR, CHUNKS, COLLECTION, MODELE_EMBEDDING, OLLAMA_URL

TAILLE_LOT = 32


def texte_document(chunk):
    return f"title: {chunk['metadata']['titre_document']} | text: {chunk['texte']}"


def texte_question(question):
    # Testé sur 254 questions : « question answering » > « search result ».
    return f"task: question answering | query: {question}"


def generer_embeddings(textes):
    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": MODELE_EMBEDDING, "input": textes},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["embeddings"]


def ouvrir_collection(reinitialiser=False):
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if reinitialiser:
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"})


def main():
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    print(f"Chunks à indexer : {len(chunks)}")

    collection = ouvrir_collection(reinitialiser=True)
    debut = time.time()
    for i in range(0, len(chunks), TAILLE_LOT):
        lot = chunks[i:i + TAILLE_LOT]
        embeddings = generer_embeddings([texte_document(c) for c in lot])
        collection.upsert(
            ids=[c["id"] for c in lot],
            documents=[c["texte"] for c in lot],
            embeddings=embeddings,
            metadatas=[c["metadata"] for c in lot],
        )
        print(f"  {min(i + TAILLE_LOT, len(chunks))}/{len(chunks)}", end="\r")

    print(f"\nIndexation terminée en {time.time() - debut:.0f} s")
    print(f"Total dans ChromaDB : {collection.count()}")


if __name__ == "__main__":
    main()
