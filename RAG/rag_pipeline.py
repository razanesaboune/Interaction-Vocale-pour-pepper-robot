"""
Construit toute la base de connaissances RAG en une commande.

    python rag_pipeline.py              # nettoyage + chunking + indexation + évaluation
    python rag_pipeline.py --sans-eval  # sans l'évaluation

Prérequis : le cache HTML (data/html_cache) rempli par rag_scraper_selenium.py
et Ollama lancé avec le modèle embeddinggemma.
"""

import sys
import time

import rag_chunking
import rag_evaluation
import rag_indexer
import rag_nettoyage

ETAPES = [
    ("1/4 Nettoyage et organisation", rag_nettoyage.main),
    ("2/4 Segmentation en chunks", rag_chunking.main),
    ("3/4 Indexation ChromaDB", rag_indexer.main),
    ("4/4 Évaluation", rag_evaluation.main),
]

if __name__ == "__main__":
    etapes = ETAPES[:3] if "--sans-eval" in sys.argv else ETAPES
    sys.argv = sys.argv[:1]
    for nom, fonction in etapes:
        print(f"\n{'=' * 60}\n{nom}\n{'=' * 60}")
        debut = time.time()
        fonction()
        print(f"({time.time() - debut:.0f} s)")
