"""
Étape 4 – Évaluation de la recherche RAG avec eval/questions.json.

Pour chaque question :
  - « reponses »  : passages exacts qui doivent figurer dans un chunk retrouvé
                    (vérifiés au préalable dans la base : aucune réponse inventée) ;
  - « documents » : fragments d'identifiant / URL du document attendu.
Un chunk est pertinent s'il satisfait les deux critères fournis.

Mesures : hit@1, hit@3, hit@5 (au moins un chunk pertinent dans les k premiers)
et MRR@10, pour les modes dense, bm25 et hybride, globalement et par thème.

    python rag_evaluation.py               # les 3 modes
    python rag_evaluation.py hybride       # un seul mode
"""

import json
import sys
from collections import defaultdict

from rag_commun import CHUNKS, QUESTIONS, RESULTATS_EVAL, normaliser_texte
from rag_recherche import Recherche

K_MAX = 10


def norm(t): 
    return normaliser_texte(t).replace("’", " ")


def pertinent(chunk, q):
    texte = norm(chunk["texte"])
    meta = chunk["metadata"]
    ok_rep = not q.get("reponses") or any(norm(r) in texte for r in q["reponses"])
    cible = (meta.get("doc_id", "") + " " + meta.get("urls_associees", "")).lower()
    ok_doc = not q.get("documents") or any(f.lower() in cible for f in q["documents"])
    return ok_rep and ok_doc


def valider(questions, chunks):
    """Chaque question doit avoir au moins un chunk pertinent dans la base."""
    invalides = []
    for i, q in enumerate(questions):
        n = sum(pertinent(c, q) for c in chunks)
        q["nb_chunks_pertinents"] = n
        if n == 0:
            invalides.append((i, q["question"]))
    return invalides


def evaluer(recherche, questions, mode):
    resultats, details = defaultdict(list), []
    for q in questions:
        res = recherche.rechercher(q["question"], k=K_MAX, mode=mode)
        rang = next((r + 1 for r, c in enumerate(res) if pertinent(c, q)), None)
        for cle in ("global", q["theme"]):
            resultats[cle].append(rang)
        details.append({
            "question": q["question"], "theme": q["theme"], "rang": rang,
            "top3": [f"{c['metadata']['titre_document'][:60]} > {c['metadata']['section'][:40]}"
                     for c in res[:3]],
        })
    return resultats, details


def mesures(rangs):
    n = len(rangs)
    return {
        "n": n,
        "hit@1": round(sum(1 for r in rangs if r and r <= 1) / n, 3),
        "hit@3": round(sum(1 for r in rangs if r and r <= 3) / n, 3),
        "hit@5": round(sum(1 for r in rangs if r and r <= 5) / n, 3),
        "mrr@10": round(sum(1 / r for r in rangs if r) / n, 3),
    }


def main():
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    invalides = valider(questions, chunks)
    print(f"{len(questions)} questions, {len(invalides)} sans réponse dans la base")
    for i, q in invalides:
        print(f"  ! [{i}] {q}")
    questions = [q for q in questions if q["nb_chunks_pertinents"]]

    modes = sys.argv[1:] or ["dense", "bm25", "hybride"]
    recherche = Recherche()
    sortie = {"nb_questions": len(questions), "questions_invalides": [q for _, q in invalides],
              "modes": {}}
    for mode in modes:
        res, details = evaluer(recherche, questions, mode)
        par_theme = {t: mesures(r) for t, r in sorted(res.items()) if t != "global"}
        sortie["modes"][mode] = {"global": mesures(res["global"]), "par_theme": par_theme,
                                 "echecs_top5": [d for d in details if not d["rang"] or d["rang"] > 5]}
        g = sortie["modes"][mode]["global"]
        print(f"\n== {mode:8s} hit@1 {g['hit@1']:.3f}  hit@3 {g['hit@3']:.3f}  "
              f"hit@5 {g['hit@5']:.3f}  MRR {g['mrr@10']:.3f}")
        for t, m in par_theme.items():
            print(f"   {t:22s} n={m['n']:3d}  hit@5 {m['hit@5']:.2f}  MRR {m['mrr@10']:.2f}")

    RESULTATS_EVAL.write_text(json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")
    meilleur = max(sortie["modes"], key=lambda m: sortie["modes"][m]["global"]["mrr@10"])
    echecs = sortie["modes"][meilleur]["echecs_top5"]
    print(f"\nÉchecs (top 5) du mode {meilleur} : {len(echecs)}")
    for e in echecs:
        print(f"  - [{e['theme']}] {e['question']}  (rang {e['rang']})")
        print(f"      trouvé : {e['top3'][0]}")


if __name__ == "__main__":
    main()
