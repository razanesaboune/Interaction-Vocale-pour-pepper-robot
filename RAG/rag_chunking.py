"""
Étape 2 – Segmentation des documents nettoyés en chunks autonomes.

Entrée : data/kb/documents_nettoyes.json
Sortie : data/kb/chunks.json, data/kb/stats_chunks.json

Principe :
  - découpage selon la structure du document (titres « ## »), pas selon un
    nombre fixe de caractères ;
  - petites sections voisines regroupées, grandes sections coupées à des
    frontières de lignes / phrases (jamais en plein mot) ;
  - chaque chunk commence par un en-tête de contexte (document, type,
    section, fiche résumée pour une formation, date pour un article) afin
    d'être compréhensible seul ;
  - un même bloc de texte présent sur plusieurs pages (ex. conditions
    d'admission communes aux parcours ingénieur) n'est indexé qu'une fois,
    avec la liste de toutes les pages concernées (relations conservées) ;
  - métadonnées : catégorie, sous-catégorie, type, source, URL, mots-clés…
"""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict

from rag_commun import (CHUNKS, DOCUMENTS_NETTOYES, STATS_CHUNKS,
                        normaliser_texte, tokens)

CIBLE = 900          # taille visée du corps d'un chunk (caractères)
MAX = 1400           # au-delà, la section est coupée
MIN = 280            # en dessous, la section est regroupée avec la suivante
MIN_DOUBLON = 200    # taille minimale d'un bloc pour la fusion des doublons
# Fiche résumée (durée, coût, campus…) répétée dans chaque chunk d'une formation.
FICHE_DANS_CHAQUE_CHUNK = True     # testé : MRR 0,782 contre 0,728 sans

TYPES_LISIBLES = {
    "fiche_formation": "Fiche formation", "formation_courte": "Formation continue courte",
    "page_formation": "Présentation de formations", "article": "Actualité",
    "evenement": "Événement", "fiche_metier": "Fiche métier", "faq": "FAQ",
    "page_legale": "Informations légales", "annuaire": "Annuaire",
    "page_informative": "Page d'information",
}
CATEGORIES_LISIBLES = {
    "formations": "Formations", "admissions_financement": "Admissions et financement",
    "campus_contacts": "Campus et contacts", "ecole_institution": "L'école",
    "international": "International", "entreprises_alternance": "Entreprises et alternance",
    "vie_etudiante": "Vie étudiante", "recherche_innovation": "Recherche et innovation",
    "metiers_orientation": "Métiers et orientation",
    "informations_legales": "Informations légales",
}

# Lexique métier : mot-clé lisible -> motif (texte normalisé, sans accents).
LEXIQUE = [
    ("alternance", r"alternan"), ("apprentissage", r"apprenti"),
    ("temps plein", r"temps plein"), ("cybersécurité", r"cyber ?securite|\bcyber\b"),
    ("intelligence artificielle", r"intelligence artificielle|\bia\b"),
    ("data", r"\bdata\b|donnees"), ("big data", r"big data"),
    ("machine learning", r"machine learning|deep learning"),
    ("robotique", r"robot"), ("réseaux", r"reseaux"), ("cloud", r"\bcloud\b"),
    ("devops", r"devops"), ("développement web", r"developpe\w* web|full ?stack"),
    ("réalité virtuelle / jeux vidéo", r"jeux? video|realite virtuelle|\bvr\b|\bxr\b"),
    ("business analyse", r"business analy"), ("smart building", r"smart|domotique|green building|\bbim\b"),
    ("admission", r"admission"), ("candidature", r"candidat"),
    ("concours GalaxY", r"galaxy"), ("Parcoursup", r"parcoursup"),
    ("frais de scolarité", r"frais|tarif|\d ?€|euros|cout"),
    ("bourse", r"bourse"), ("CPF", r"\bcpf\b"), ("VAE", r"\bvae\b|validation des acquis"),
    ("OPCO", r"\bopco\b"), ("Erasmus+", r"erasmus"), ("international", r"internationa|etranger"),
    ("campus Cergy", r"cergy"), ("campus Pontoise", r"pontoise"),
    ("campus Paris", r"paris|montparnasse"), ("portes ouvertes", r"portes ouvertes|\bjpo\b"),
    ("handicap", r"handicap"), ("logement", r"logement"), ("vie associative", r"association|assos\b|\bbde\b"),
    ("entreprises partenaires", r"partenai"), ("taxe d'apprentissage", r"taxe d apprentissage"),
    ("RNCP", r"\brncp\b"), ("CTI", r"\bcti\b"), ("diplôme d'ingénieur", r"diplome d ingenieur|titre ingenieur"),
    ("Bac+3", r"bac ?\+ ?3"), ("Bac+5", r"bac ?\+ ?5"), ("BTS / BUT", r"\bbts\b|\bbut\b|\bdut\b"),
    ("licence", r"\blicence\b"), ("prépa intégrée", r"preparatoire|prepa"),
    ("stage", r"\bstages?\b"), ("salaire", r"salaire|remuneration"),
    ("débouchés", r"debouche|metiers"), ("contact", r"@esiee-it\.fr|telephone|\b0\d( ?\d\d){4}\b"),
    ("Coding Factory", r"coding factory"), ("agilité / SAFe", r"\bsafe\b|agil|scrum"),
    ("recherche", r"recherche|laboratoire|integr ?it"), ("entrepreneuriat", r"entrepreneur|startup"),
    ("alumni", r"alumni|diplomes"), ("insertion professionnelle", r"insertion|taux d emploi|en emploi"),
]
LEXIQUE = [(nom, re.compile(m)) for nom, m in LEXIQUE]


# ------------------------------------------------------------- SECTIONS

def sections_du_document(contenu):
    """[(chemin de titres, [lignes])] ; titres consécutifs = chemin « A > B ».

    Aucun titre n'est perdu : dans une longue suite de titres sans texte,
    les premiers passent dans le corps de la section ; des titres en fin de
    document forment une section à eux seuls.
    """
    sections, titres, lignes = [], [], []

    def fermer():
        if len(titres) > 2:
            corps = ["## " + t for t in titres[:-2]] + lignes
            sections.append((titres[-2:], corps))
        else:
            sections.append((titres, lignes))

    for l in contenu.split("\n"):
        if l.startswith("## "):
            if lignes:
                fermer()
                titres, lignes = [], []
            titres = titres + [l[3:].strip()]
        elif l.strip():
            lignes.append(l)
    if lignes:
        fermer()
    elif titres:
        sections.append((titres[:1], ["## " + t for t in titres[1:]] or ["## " + titres[0]]))
    return sections


def couper_ligne(ligne, taille):
    """Coupe une ligne trop longue à des fins de phrases."""
    phrases = re.split(r"(?<=[.!?;])\s+", ligne)
    morceaux, cur = [], ""
    for p in phrases:
        if cur and len(cur) + len(p) + 1 > taille:
            morceaux.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        morceaux.append(cur)
    return morceaux


def couper_section(lignes, cible=CIBLE):
    """Découpe une grande section en parties d'environ CIBLE caractères."""
    unites = []
    for l in lignes:
        unites.extend(couper_ligne(l, cible) if len(l) > MAX else [l])
    # Une phrase d'introduction (« … : ») suivie d'une liste est répétée
    # en tête des parties suivantes pour garder le contexte de la liste.
    parties, cur, intro = [], [], None
    for u in unites:
        if not u.startswith("- ") and u.rstrip().endswith(":"):
            intro = u
        elif not u.startswith("- "):
            intro = None
        if cur and len("\n".join(cur)) + len(u) > cible:
            parties.append(cur)
            cur = [f"{intro} (suite)"] if intro and u.startswith("- ") else []
        cur.append(u)
    if cur:
        parties.append(cur)
    return parties


def blocs_du_document(doc):
    """Liste de (titre de section, texte du corps)."""
    blocs = []
    attente_titre, attente = [], []

    def vider():
        if attente:
            blocs.append((" / ".join(dict.fromkeys(attente_titre)) or "Présentation",
                          "\n".join(attente)))
        attente_titre.clear()
        attente.clear()

    for titres, lignes in sections_du_document(doc["contenu"]):
        nom = " > ".join(titres) if titres else "Présentation"
        corps = "\n".join(lignes)
        if len(corps) > MAX:
            vider()
            parties = couper_section(lignes, 400 if doc["type_document"] == "annuaire" else CIBLE)
            for i, p in enumerate(parties):
                suffixe = f" (partie {i + 1}/{len(parties)})" if len(parties) > 1 else ""
                blocs.append((nom + suffixe, "\n".join(p)))
            continue
        taille_attente = len("\n".join(attente))
        if attente and taille_attente + len(corps) > CIBLE:
            vider()
        # Le titre est gardé dans le corps quand plusieurs sections sont regroupées.
        attente_titre.append(nom)
        attente.append((f"## {titres[-1]}\n" if titres else "") + corps if attente or len(corps) < MIN else corps)
        if len("\n".join(attente)) >= MIN:
            vider()
    vider()

    # Dernier bloc trop petit : rattaché au précédent.
    if len(blocs) >= 2 and len(blocs[-1][1]) < MIN // 2 and \
            len(blocs[-2][1]) + len(blocs[-1][1]) <= MAX:
        t, c = blocs.pop()
        t0, c0 = blocs.pop()
        blocs.append((f"{t0} / {t}", f"{c0}\n## {t}\n{c}"))
    return blocs


# ------------------------------------------------------------- CONTEXTE

def entete(doc, section, premier=True):
    lignes = [f"Document : {doc['titre']}",
              f"Type : {TYPES_LISIBLES.get(doc['type_document'], doc['type_document'])}"
              f" | Catégorie : {CATEGORIES_LISIBLES.get(doc['categorie'], doc['categorie'])}"]
    if doc["informations_cles"] and (FICHE_DANS_CHAQUE_CHUNK or premier):
        lignes.append("Informations clés : " + " ; ".join(doc["informations_cles"]))
    if doc["date_publication"]:
        lignes.append(f"Publié le {doc['date_publication']}")
    if section and section != "Présentation":
        lignes.append(f"Section : {section}")
    return "\n".join(lignes)


# ------------------------------------------------------------- MOTS-CLÉS

def formes_lisibles(chunks):
    """Token normalisé -> forme la plus fréquente dans le texte d'origine."""
    formes = defaultdict(Counter)
    for c in chunks:
        for mot in re.findall(r"[\w+#'’-]+", c["contenu"]):
            mot_l = mot.lower().strip("'’-")
            t = tokens(mot_l)
            if len(t) == 1:
                formes[t[0]][mot_l] += 1
    return {t: f.most_common(1)[0][0] for t, f in formes.items()}


def ajouter_mots_cles(chunks):
    docs_tokens = [Counter(tokens(c["contenu"])) for c in chunks]
    df = Counter()
    for tf in docs_tokens:
        df.update(tf.keys())
    n = len(chunks)
    formes = formes_lisibles(chunks)
    for c, tf in zip(chunks, docs_tokens):
        texte_n = normaliser_texte(c["contenu"])
        lex = [nom for nom, motif in LEXIQUE if motif.search(texte_n)]
        total = sum(tf.values()) or 1
        # Mots présents dans au moins 2 chunks (évite fautes et mots isolés),
        # mais pas dans plus de 15 % (trop banals).
        scores = {t: (f / total) * math.log(n / df[t]) for t, f in tf.items()
                  if len(t) > 4 and not t.isdigit() and 2 <= df[t] < n * 0.15}
        top = [formes.get(t, t) for t, _ in sorted(scores.items(), key=lambda x: -x[1])[:5]]
        mots = list(dict.fromkeys(lex[:8] + [m for m in top if m not in lex]))
        c["metadata"]["mots_cles"] = ", ".join(mots[:12])


# ---------------------------------------------------------------- MAIN

def main():
    documents = json.loads(DOCUMENTS_NETTOYES.read_text(encoding="utf-8"))
    chunks, par_empreinte = [], {}
    stats = Counter()

    for doc in documents:
        blocs = blocs_du_document(doc)
        gardes = []
        for section, corps in blocs:
            # Même section ET même texte : sinon le titre (qui peut porter
            # une information, ex. un nom) serait perdu.
            empreinte = hashlib.sha256(
                normaliser_texte(section + "\n" + corps).encode()).hexdigest()
            if len(corps) >= MIN_DOUBLON and empreinte in par_empreinte:
                original = par_empreinte[empreinte]
                meta = original["metadata"]
                if doc["url"] not in meta["_urls"]:
                    meta["_urls"].append(doc["url"])
                    meta["_docs"].append(doc["titre"])
                stats["chunks_doublons_fusionnes"] += 1
                continue
            chunk = {
                "contenu": corps,
                "section": section,
                "metadata": {
                    "doc_id": doc["id"],
                    "titre_document": doc["titre"],
                    "section": section,
                    "categorie": doc["categorie"],
                    "sous_categorie": doc["sous_categorie"],
                    "type_document": doc["type_document"],
                    "source": doc["source"],
                    "url": doc["url"],
                    "niveau": doc["niveau"],
                    "campus": doc["campus"],
                    "modalite": doc["modalite"],
                    "date_publication": doc["date_publication"],
                    "date_extraction": doc["date_extraction"],
                    "pages_liees": " ; ".join(doc["pages_liees"][:15]),
                    "_urls": list(doc["urls"]),
                    "_docs": [doc["titre"]],
                },
                "_doc": doc,
            }
            par_empreinte[empreinte] = chunk
            gardes.append(chunk)
        for i, c in enumerate(gardes):
            c["id"] = f"{doc['id']}#{i + 1:02d}"
            c["metadata"]["position"] = i + 1
            c["metadata"]["nb_chunks_document"] = len(gardes)
        chunks.extend(gardes)

    # Texte final : en-tête de contexte + corps (+ documents qui partagent le bloc).
    for c in chunks:
        meta = c["metadata"]
        autres = meta["_docs"][1:]
        texte = entete(c["_doc"], c["section"], c["metadata"]["position"] == 1) + "\n\n" + c["contenu"]
        if autres:
            texte += "\n\nCe passage figure aussi dans : " + " ; ".join(autres)
        c["texte"] = texte
        meta["urls_associees"] = " ; ".join(meta["_urls"])
        meta["documents_associes"] = " ; ".join(autres)
        meta["nb_caracteres"] = len(texte)

    ajouter_mots_cles(chunks)

    # Contrôle de non-perte : chaque ligne d'un document doit se retrouver
    # dans au moins un chunk (le sien, ou le chunk partagé s'il a été fusionné).
    texte_par_doc = defaultdict(str)
    for c in chunks:
        for titre in c["metadata"]["_docs"]:
            texte_par_doc[titre] += "\n" + normaliser_texte(c["texte"])
    perdues = []
    for doc in documents:
        tout = texte_par_doc[doc["titre"]]
        for l in doc["contenu"].split("\n"):
            debut = normaliser_texte(re.sub(r"^(## |- )", "", l))[:60]
            if debut and debut not in tout:
                perdues.append(f"{doc['id']} : {l[:80]}")
    stats["lignes_perdues"] = len(perdues)
    for p in perdues[:20]:
        print("  ligne perdue :", p)

    sortie = []
    for c in chunks:
        meta = {k: v for k, v in c["metadata"].items() if not k.startswith("_")}
        sortie.append({"id": c["id"], "texte": c["texte"], "contenu": c["contenu"],
                       "metadata": meta})
    CHUNKS.write_text(json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")

    tailles = sorted(len(c["texte"]) for c in sortie)
    resume = {
        "documents": len(documents),
        "chunks": len(sortie),
        "chunks_doublons_fusionnes": stats["chunks_doublons_fusionnes"],
        "lignes_perdues_au_decoupage": stats["lignes_perdues"],
        "chunks_partages_par_plusieurs_pages": sum(1 for c in sortie if c["metadata"]["documents_associes"]),
        "taille_caracteres": {"min": tailles[0], "mediane": tailles[len(tailles) // 2],
                              "moyenne": round(sum(tailles) / len(tailles)),
                              "max": tailles[-1]},
        "par_categorie": dict(Counter(c["metadata"]["categorie"] for c in sortie).most_common()),
        "par_type": dict(Counter(c["metadata"]["type_document"] for c in sortie).most_common()),
    }
    STATS_CHUNKS.write_text(json.dumps(resume, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resume, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
