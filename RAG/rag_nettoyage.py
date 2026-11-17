"""
Étape 1 – Nettoyage et organisation des pages scrapées.

Entrée  : data/html_cache/ (HTML brut de chaque page, avec son URL)
Sortie  : data/kb/documents_nettoyes.json, data/kb/stats_nettoyage.json
Le fichier data/documents.json d'origine n'est pas modifié.

Règles :
  - aucune phrase n'est réécrite : on supprime seulement des lignes
    techniques (libellés du CMS, boutons, messages d'erreur, encarts de liens) ;
  - pages d'erreur / pages de listes exclues ;
  - pages au contenu identique fusionnées (toutes les URL sont gardées) ;
  - les liens vers d'autres pages (articles liés, formations conseillées)
    sont retirés du texte mais gardés dans « pages_liees » ;
  - chaque document reçoit : url, catégorie, sous-catégorie, type, date…
"""

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from rag_commun import (CACHE_DIR, DOCUMENTS_NETTOYES, KB_DIR, SOURCE,
                        STATS_NETTOYAGE, normaliser_texte)
import rag_scraper_selenium as scraper

# ------------------------------------------------------------ LIGNES À RETIRER

# Libellés techniques du CMS (jamais du contenu).
LABELS_CMS = re.compile(
    r"^(page content|detail news/event top|bloc (rouge|violet|bleu|vert|jaune|"
    r"orange|gris|blanc|noir)|colonne (gauche|droite)\b.*|event registration "
    r"form|marketing form|texte|vide|image|vid[ée]o|formulaire|\.)$", re.I)
# Liens « Voir les formations sur Pontoise », « Voir la vidéo du campus »…
LIENS_VOIR = re.compile(r"^(voir|d[ée]couvr\w*) (les|la|le|nos|toutes?) "
                        r"(formations?|vid[ée]o|programmes?)\b.{0,40}$", re.I)

# Boutons / liens de navigation.
NAVIGATION = {
    "toutes nos actualites", "voir tous les evenements", "s inscrire",
    "prendre rendez-vous", "prendre rendez vous", "nous contacter",
    "je m inscris", "voir la video du campus", "voir la video du campus paris",
    "appeler", "chatter", "en savoir +", "decouvrir la formation",
    "decouvrir nos formations", "voir les formations", "inscription",
    "telecharger la brochure", "telechargez le guide decrocher une alternance",
    "decouvrez les tips cv/lettre en videos",
}
# Onglets « Description / Modalités d'admission / Programme » en tête de fiche.
ONGLETS = {"description", "modalites d admission", "programme", "admission",
           "debouches", "informations pratiques", "candidature"}

ERREURS = ("vous n'êtes pas autorisé(e) à accéder à cette page",
           "la page demandée n'a pas pu être trouvée")
TITRES_ERREUR = {"Accès refusé", "Page non trouvée"}

# Sections qui ne contiennent que des liens vers d'autres pages.
SECTIONS_LIENS = re.compile(
    r"^## (autres formations pouvant vous plaire|consultez nos formations|"
    r"d autres tips|à lire aussi|a lire aussi|nos autres formations|"
    r"ces articles peuvent vous int[ée]resser|articles? li[ée]s?)", re.I)

DATE_CARTE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
DATE_PUBLICATION = re.compile(r"publi[ée]e? le (\d{1,2}(?:er)? \w+ \d{4})", re.I)
MISE_A_JOUR = re.compile(r"^page actualis[ée]e en ?: ?(.+)$", re.I)

# --------------------------------------------------------- CLASSIFICATION

# (catégorie, motif sur titre + URL), dans l'ordre de priorité.
CATEGORIES = [
    ("informations_legales", r"mentions legales|accessibilite|eco-conception|"
                             r"eco conception|reglement|charte|plan du site|cookies"),
    ("campus_contacts", r"campus|contact|annuaire|equipe dediee|votre equipe"),
    ("international", r"erasmus|internationa|etranger|exchange|mobilite|mona|"
                      r"study|madrid|riga|double diplome"),
    ("admissions_financement", r"admission|candidat|inscription|bourse|financ|"
                               r"cpf|vae|aide|frais|jpo|portes ouvertes|rdv live|"
                               r"orientation|parcoursup|concours"),
    ("entreprises_alternance", r"alternan|entreprise|apprenti|taxe|recrut|"
                               r"partenai|alumni|emploi|carriere|cv|lettre de "
                               r"motivation|entretien|stage|ils nous font confiance"),
    ("recherche_innovation", r"recherche|laboratoire|integr ?it|publication|"
                             r"project lab|innovation|entrepreneuriat|hackathon|"
                             r"game jam|projets? d etudes"),
    ("vie_etudiante", r"association|assos|vie etudiante|logement|budget|handicap|"
                      r"etudiant\.e\.s|sport|bde|soiree|skills"),
    ("metiers_orientation", r"^devenir|^devenez|metier|battle|salaire"),
    ("ecole_institution", r"."),
]

SOUS_CATEGORIES = {
    "formations": [
        ("formation_continue", r"safe|agilite|afon0|formation continue|executive"),
        ("coding_factory", r"coding factory|lead dev|jeux video|concepteur developpeur"),
        ("programme_ingenieur", r"cycle ingenieur|cycle preparatoire|prepa|"
                                r"programme ingenieur|ecole d ingenieurs|1ere annee"),
        ("bachelor_bac3", r"bac ?\+ ?3|bachelor|licence"),
        ("expert_bac5", r"bac ?\+ ?5|expert|mastere|manager|consultant"),
        ("domaine_de_formation", r"."),
    ],
    "admissions_financement": [
        ("bourses_aides", r"bourse|aide"),
        ("financement", r"financ|cpf|frais"),
        ("vae", r"vae|validation des acquis"),
        ("portes_ouvertes_rdv", r"portes ouvertes|jpo|rdv|rendez-vous|live"),
        ("candidature", r"candidat|inscription|admission|concours|."),
    ],
    "international": [
        ("erasmus", r"erasmus"), ("etudiants_internationaux", r"internationa|exchange|study"),
        ("mobilite_apprentis", r"mona|mobilite"), ("international", r"."),
    ],
    "entreprises_alternance": [
        ("recherche_alternance", r"cv|lettre|entretien|trouver|decrocher|sites"),
        ("relations_entreprises", r"entreprise|partenai|recrut|taxe|confiance"),
        ("alumni_emploi", r"alumni|emploi|carriere|salaire"),
        ("alternance", r"."),
    ],
    "metiers_orientation": [
        ("fiche_metier", r"^devenir|^devenez"), ("guide_metiers", r"."),
    ],
}

MOTIFS_FORMATION_SLUG = re.compile(
    r"^(bac|cycle-|programme-ingenieur|licence|prepa-|prepa$|1ere|formation-|"
    r"bachelor|mastere|safe|leading|agilite|coding-factory|la-coding-factory|"
    r"cybersecurite|la-cybersecurite|ia-data|informatique|business-analyse|"
    r"vr-jeux-video|robotique|programmes-experts|gestion-de-projets)")
# Titres de pages qui présentent une offre de formation.
MOTIFS_FORMATION_TITRE = re.compile(
    r"^formation |devenez un expert avec esiee|coding factory|classe dediee")
# Pages à classer d'office (titre normalisé -> catégorie).
CATEGORIE_FORCEE = [
    (r"ecole a impact des entreprises du futur", "ecole_institution"),
    (r"^(pontoise|paris montparnasse|paris ou|campus|cergy)", "campus_contacts"),
    (r"espace .?candidature", "admissions_financement"),
    (r"devenez partenaire", "entreprises_alternance"),
]


def type_document(page, slug, titre_n):
    url = page["url"]
    if "/actualites/" in url:
        return "article"
    if "/evenements/" in url:
        return "evenement"
    if re.search(r"safe|agilite|afon0", slug):
        return "formation_courte"
    if page["fiche"]:
        return "fiche_formation"
    if re.search(r"faq|foire aux questions", titre_n):
        return "faq"
    if re.search(r"^devenir|^devenez|metiers? ", titre_n) and \
            not re.search(r"partenaire|expert avec", titre_n):
        return "fiche_metier"
    if re.search(r"mentions legales|accessibilite|eco-conception|reglement|plan du site", titre_n):
        return "page_legale"
    if MOTIFS_FORMATION_SLUG.search(slug) or MOTIFS_FORMATION_TITRE.search(titre_n):
        return "page_formation"
    return "page_informative"


def classer(page, type_doc, slug, titre_n):
    cible = f"{titre_n} {slug.replace('-', ' ')}"
    if type_doc in ("fiche_formation", "formation_courte", "page_formation"):
        cat = "formations"
    elif type_doc == "fiche_metier":
        cat = "metiers_orientation"
    elif type_doc == "page_legale":
        cat = "informations_legales"
    else:
        cat = next(c for c, m in CATEGORIES if re.search(m, cible))
    if type_doc not in ("article", "evenement"):
        for motif, forcee in CATEGORIE_FORCEE:
            if re.search(motif, titre_n):
                cat = forcee
                break
    debut = normaliser_texte(" ".join(page["lignes"][:15]))
    sous = cat
    for nom, motif in SOUS_CATEGORIES.get(cat, []):
        if re.search(motif, cible) or (cat == "formations" and nom == "coding_factory"
                                       and "coding factory" in debut):
            sous = nom
            break
    if type_doc == "article" and sous == cat:
        sous = "actualite"
    if type_doc == "evenement" and sous == cat:
        sous = "evenement"
    return cat, sous


# ------------------------------------------------------------- NETTOYAGE

def cle(ligne):
    return normaliser_texte(re.sub(r"^(## |- )", "", ligne)).strip(" :.!?")


CODE_PARASITE = re.compile(r"%3Cmeta%20charset%3D%22UTF-8%22%20%2F%3E|"
                           r"Bouton \d+( \(nouveau\))? ")


def nettoyer_lignes(lignes, stats):
    """Retourne (lignes gardées, pages liées, date de publication, mise à jour)."""
    # Fragments de code abîmés présents dans le HTML du site (pas du contenu).
    propres = []
    for l in lignes:
        l2 = CODE_PARASITE.sub("", l).strip()
        if l2 != l:
            stats["code_parasite"] += 1
        if l2 and l2 not in ("-", "##"):
            propres.append(re.sub(r"^(- |## )\s+", r"\1", l2))
    lignes = propres
    gardees, liees = [], []
    date_pub = maj = None
    i = 0
    while i < len(lignes):
        l = lignes[i]
        k = cle(l)
        brut = re.sub(r"^(## |- )", "", l)

        m = DATE_PUBLICATION.search(l)
        if m and date_pub is None:
            date_pub = m.group(1)
        m = MISE_A_JOUR.match(brut)
        if m:
            maj = m.group(1)
            stats["mise_a_jour"] += 1
            i += 1
            continue
        if LABELS_CMS.match(brut.strip()):
            stats["labels_cms"] += 1
            i += 1
            continue
        if k in NAVIGATION or (l.startswith("- ") and k in ONGLETS) or \
                (not l.startswith("## ") and LIENS_VOIR.match(brut.strip())) or \
                (not l.startswith("## ") and len(brut) < 45 and brut.rstrip().endswith("→")):
            stats["navigation"] += 1
            i += 1
            continue
        # Carte d'article lié : « 02.02.2023 » puis « ## Titre ».
        if DATE_CARTE.match(l) and i + 1 < len(lignes) and lignes[i + 1].startswith("## "):
            liees.append(lignes[i + 1][3:])
            stats["cartes_liens"] += 1
            i += 2
            continue
        # Section composée uniquement de liens.
        if SECTIONS_LIENS.match("## " + k if l.startswith("## ") else ""):
            j = i + 1
            while j < len(lignes) and not lignes[j].startswith("## "):
                if not DATE_CARTE.match(lignes[j]) and len(lignes[j]) < 150:
                    liees.append(re.sub(r"^- ", "", lignes[j]))
                j += 1
            stats["sections_liens"] += 1
            i = j
            continue
        gardees.append(l)
        i += 1

    # Les titres sans texte sont gardés : certains portent l'information
    # (« Programme Ingénieur → Claire KRUCH », « Chargée des admissions »).
    return gardees, liees, date_pub, maj


def construire_contenu(page, lignes):
    titre_n = normaliser_texte(page["titre"])
    lignes = [l for l in lignes if normaliser_texte(re.sub(r"^(## |- )", "", l)) != titre_n]
    parties = []
    corps = "\n".join(lignes)
    desc = page["description"]
    if desc and not re.search(r"[.!?…)»'\x22]$", desc):
        desc += "…"          # description coupée par le site
    if desc and normaliser_texte(desc[:60]) not in normaliser_texte(corps):
        parties.append(desc)
    if page["fiche"]:
        parties.append("## Informations clés\n" + "\n".join("- " + x for x in page["fiche"]))
    parties.append(corps)
    if page.get("contacts"):
        parties.append("## Contacts\n" + "\n".join("- " + c for c in page["contacts"]))
    return "\n".join(p for p in parties if p).strip()


def valeur_fiche(fiche, nom):
    for x in fiche:
        if normaliser_texte(x).startswith(normaliser_texte(nom)):
            return x.split(":", 1)[1].strip()
    return ""


def slug_de(url):
    chemin = urlparse(url).path.strip("/").split("/")
    return chemin[-1] if chemin else "accueil"


def identifiant(url):
    chemin = urlparse(url).path.strip("/")
    chemin = re.sub(r"^fr/?", "", chemin) or "accueil"
    return re.sub(r"[^a-z0-9]+", "-", chemin.lower()).strip("-")[:80]


def charger_pages():
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    pages = []
    for url, nom in index.items():
        chemin = CACHE_DIR / nom
        if not chemin.exists():
            continue
        page = scraper.extraire_page(chemin.read_text(encoding="utf-8"), url)
        if page:
            page["date_extraction"] = datetime.fromtimestamp(
                chemin.stat().st_mtime).strftime("%Y-%m-%d")
            pages.append(page)
    return pages


def main():
    KB_DIR.mkdir(parents=True, exist_ok=True)
    pages = charger_pages()
    stats = Counter()
    stats["pages_cache"] = len(pages)
    exclues = Counter()

    documents, annuaire, annuaire_urls = [], [], []
    for page in pages:
        chemin = urlparse(page["url"]).path
        if chemin in scraper.PAGES_LISTES or not scraper.url_valide(page["url"]):
            exclues["page_de_liste"] += 1
            continue
        texte = " ".join(page["lignes"]).lower()
        if page["titre"] in TITRES_ERREUR or (
                len(page["lignes"]) <= 3 and any(e in texte for e in ERREURS)):
            exclues["page_erreur"] += 1
            continue
        stats["lignes_initiales"] += len(page["lignes"])
        lignes, liees, date_pub, maj = nettoyer_lignes(page["lignes"], stats)

        # Fiche d'une personne (nom + coordonnées) -> annuaire commun.
        if page.get("contacts") and len("\n".join(lignes)) < 120:
            for c in page["contacts"]:
                ligne = c if c.startswith(page["titre"]) else f"{page['titre']} : {c}"
                if ligne not in annuaire:
                    annuaire.append(ligne)
                    annuaire_urls.append(page["url"])
            exclues["fiche_contact_vers_annuaire"] += 1
            continue

        contenu = construire_contenu(page, lignes)
        if len(contenu) < 30:            # garde les fiches campus (adresse)
            exclues["contenu_trop_court"] += 1
            continue

        slug = slug_de(page["url"])
        titre_n = normaliser_texte(page["titre"])
        type_doc = type_document(page, slug, titre_n)
        cat, sous = classer(page, type_doc, slug, titre_n)
        niveau = re.search(r"bac ?\+ ?(\d)", titre_n)
        documents.append({
            "id": identifiant(page["url"]),
            "titre": page["titre"],
            "url": page["url"],
            "urls": [page["url"]],
            "source": SOURCE,
            "categorie": cat,
            "sous_categorie": sous,
            "type_document": type_doc,
            "description": page["description"],
            "niveau": f"Bac+{niveau.group(1)}" if niveau else "",
            "campus": valeur_fiche(page["fiche"], "Campus"),
            "modalite": valeur_fiche(page["fiche"], "Modalit"),
            "duree": valeur_fiche(page["fiche"], "Durée"),
            "informations_cles": page["fiche"],
            "date_publication": date_pub or "",
            "date_mise_a_jour": maj or "",
            "date_extraction": page["date_extraction"],
            "pages_liees": list(dict.fromkeys(liees)),
            "contenu": contenu,
        })

    # Pages au contenu identique : un seul document, toutes les URL gardées.
    par_empreinte = {}
    uniques = []
    for d in documents:
        e = hashlib.sha256(normaliser_texte(d["contenu"]).encode()).hexdigest()
        if e in par_empreinte:
            par_empreinte[e]["urls"].append(d["url"])
            exclues["doublon_exact_fusionne"] += 1
        else:
            par_empreinte[e] = d
            uniques.append(d)
    documents = uniques

    if annuaire:
        documents.append({
            "id": "annuaire-contacts", "titre": "Annuaire des contacts ESIEE-IT",
            "url": "https://www.esiee-it.fr/fr/votre-equipe-dediee",
            "urls": list(dict.fromkeys(annuaire_urls)), "source": SOURCE,
            "categorie": "campus_contacts", "sous_categorie": "annuaire",
            "type_document": "annuaire",
            "description": "Coordonnées (téléphone, email) des membres de l'équipe ESIEE-IT.",
            "niveau": "", "campus": "", "modalite": "", "duree": "",
            "informations_cles": [], "date_publication": "", "date_mise_a_jour": "",
            "date_extraction": datetime.now().strftime("%Y-%m-%d"), "pages_liees": [],
            "contenu": "Coordonnées des membres de l'équipe ESIEE-IT "
                       "(téléphone et email) :\n" + "\n".join("- " + a for a in sorted(annuaire)),
        })

    # Identifiants uniques.
    vus = Counter()
    for d in documents:
        vus[d["id"]] += 1
        if vus[d["id"]] > 1:
            d["id"] = f"{d['id']}-{vus[d['id']]}"

    ordre = ["formations", "admissions_financement", "campus_contacts",
             "ecole_institution", "international", "entreprises_alternance",
             "vie_etudiante", "recherche_innovation", "metiers_orientation",
             "informations_legales"]
    documents.sort(key=lambda d: (ordre.index(d["categorie"]), d["type_document"] == "article", d["titre"]))

    DOCUMENTS_NETTOYES.write_text(json.dumps(documents, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    resume = {
        "pages_dans_le_cache": len(pages),
        "documents_nettoyes": len(documents),
        "pages_exclues": dict(exclues),
        "lignes_retirees": {k: stats[k] for k in ("labels_cms", "navigation",
                                                   "cartes_liens", "sections_liens", "code_parasite",
                                                   "mise_a_jour")},
        "caracteres": sum(len(d["contenu"]) for d in documents),
        "par_categorie": dict(Counter(d["categorie"] for d in documents).most_common()),
        "par_sous_categorie": dict(Counter(f"{d['categorie']}/{d['sous_categorie']}"
                                           for d in documents).most_common()),
        "par_type": dict(Counter(d["type_document"] for d in documents).most_common()),
    }
    STATS_NETTOYAGE.write_text(json.dumps(resume, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resume, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
