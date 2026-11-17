"""
Recherche dans la base de connaissances ESIEE-IT.

Trois modes :
  - « dense »   : similarité de vecteurs (embeddinggemma + ChromaDB) ;
  - « bm25 »    : mots-clés (BM25), utile pour les noms propres, sigles,
                  montants, codes (RNCP, SAFe, GalaxY…) ;
  - « hybride » : fusion des deux classements (Reciprocal Rank Fusion).

Utilisation :
    from rag_recherche import Recherche
    r = Recherche()
    for res in r.rechercher("Combien coûte le bachelor en temps plein ?", k=4):
        print(res["score"], res["metadata"]["url"], res["texte"][:200])

En ligne de commande :
    python rag_recherche.py "Où se trouve le campus de Pontoise ?"
"""

import json
import math
import sys
from collections import Counter

from rag_commun import CHUNKS, tokens
from rag_indexer import generer_embeddings, ouvrir_collection, texte_question

RRF_K = 20          # testé : 20 légèrement meilleur que 60
CANDIDATS = 40


class BM25:
    def __init__(self, textes, k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(t)) for t in textes]
        self.longueurs = [sum(d.values()) for d in self.docs]
        self.moyenne = sum(self.longueurs) / len(self.docs)
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, question):
        q = set(tokens(question))
        res = []
        for i, (d, lg) in enumerate(zip(self.docs, self.longueurs)):
            s = 0.0
            for t in q:
                f = d.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * lg / self.moyenne))
            if s:
                res.append((i, s))
        return sorted(res, key=lambda x: -x[1])


class Recherche:
    def __init__(self):
        self.chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
        self.index = {c["id"]: i for i, c in enumerate(self.chunks)}
        self.bm25 = BM25([c["texte"] for c in self.chunks])
        self.collection = ouvrir_collection()

    def _dense(self, question, n):
        emb = generer_embeddings([texte_question(question)])[0]
        r = self.collection.query(query_embeddings=[emb], n_results=n,
                                  include=["distances"])
        return [(self.index[i], 1 - d) for i, d in zip(r["ids"][0], r["distances"][0])
                if i in self.index]

    def _bm25(self, question, n):
        return self.bm25.scores(question)[:n]

    def rechercher(self, question, k=5, mode="hybride", filtre=None):
        """filtre : dict de métadonnées à respecter, ex. {"categorie": "formations"}."""
        n = CANDIDATS if not filtre else len(self.chunks)
        if mode == "dense":
            classement = self._dense(question, n)
        elif mode == "bm25":
            classement = self._bm25(question, n)
        else:
            fusion = Counter()
            for liste in (self._dense(question, n), self._bm25(question, n)):
                for rang, (i, _) in enumerate(liste):
                    fusion[i] += 1 / (RRF_K + rang + 1)
            classement = fusion.most_common()

        resultats = []
        for i, score in classement:
            c = self.chunks[i]
            if filtre and any(c["metadata"].get(cle) != v for cle, v in filtre.items()):
                continue
            resultats.append({"id": c["id"], "score": round(score, 4),
                              "texte": c["texte"], "metadata": c["metadata"]})
            if len(resultats) == k:
                break
        return resultats


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Quels sont les campus d'ESIEE-IT ?"
    for r in Recherche().rechercher(question, k=5):
        m = r["metadata"]
        print(f"\n[{r['score']}] {m['titre_document']} > {m['section']}\n  {m['url']}")
        print("  " + r["texte"].split("\n\n", 1)[-1][:300].replace("\n", "\n  "))
