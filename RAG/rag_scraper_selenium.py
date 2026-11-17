"""
Scraping complet du site ESIEE-IT avec Selenium, pour la base RAG de Pepper.

Fonctionnement :
  1. On part de la page d'accueil et des URLs du sitemap.xml.
  2. Chrome (sans fenêtre) ouvre chaque page :
       - le HTML est gardé dans data/html_cache/ ;
       - tous les liens internes sont ajoutés à la file d'attente.
  3. Extraction du texte du contenu principal (<main>) :
       - fiche résumée des formations (Diplôme, Durée, Coût, Campus,
         dates d'inscription, contact…) ;
       - titres, paragraphes, listes, tableaux, blocs <div> ;
       - accordéons / FAQ (Objectifs, Débouchés, Indicateurs…), même repliés.
  4. On retire les lignes répétées sur beaucoup de pages (menus, boutons)
     et les pages en double.
  5. Résultat : data/documents.json -> [{titre, categorie, contenu}, ...]

Lancement (Windows, depuis le dossier du projet) :
    pepper\\Scripts\\python.exe RAG\\rag_scraper_selenium.py
    pepper\\Scripts\\python.exe RAG\\rag_scraper_selenium.py --max-pages 20   (essai)
    pepper\\Scripts\\python.exe RAG\\rag_scraper_selenium.py --visible        (voir Chrome)
    pepper\\Scripts\\python.exe RAG\\rag_scraper_selenium.py --reprendre      (après coupure)
    pepper\\Scripts\\python.exe RAG\\rag_scraper_selenium.py --depuis-cache   (ré-extraire
                                     le texte sans re-télécharger le site)
"""

import argparse
import hashlib
import json
import re
import shutil
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, deque
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString

# ---------------------------------------------------------------- RÉGLAGES

SITE = "https://www.esiee-it.fr"
DEPART = SITE + "/fr"
SITEMAP = SITE + "/sitemap.xml"
PREFIXE = "/fr"                  # on reste sur la partie française

DELAI = 2.0                      # Crawl-delay demandé par robots.txt
TIMEOUT_PAGE = 30
MAX_PAGES = 1500                 # garde-fou

DATA_DIR = Path(__file__).resolve().parent / "data"
SORTIE = DATA_DIR / "documents.json"
CACHE = DATA_DIR / "html_cache"          # HTML brut de chaque page
INDEX_CACHE = CACHE / "index.json"       # url -> fichier
ETAT = DATA_DIR / "scraping_etat.json"   # pour reprendre après une coupure

# Chemins interdits par robots.txt ou sans intérêt pour le RAG.
CHEMINS_EXCLUS = [
    "/user/", "/admin/", "/core/", "/profiles/", "/modules/",
    "/search/", "/cart/", "/checkout/", "/sites/default/files/",
    "/votre-inscription-bien-ete-enregistree",   # pages « merci »
    "/node/", "/taxonomy/", "/print/", "/fr/footer", "/fr/logo-",
]
# Pages visitées (pour trouver des liens) mais pas gardées dans le JSON :
# ce ne sont que des listes de liens vers les autres pages.
PAGES_LISTES = {
    "/fr/actualites", "/fr/evenements", "/fr/plan-du-site", "/fr/search-content",
}
EXTENSIONS_EXCLUES = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp4", ".mp3",
)

# Zones de la page à ignorer.
SELECTEURS_A_RETIRER = [
    "script", "style", "noscript", "svg", "iframe", "form", "img", "picture",
    "video", "header", "footer", "nav", "#header", "#footer", "#search-layer",
    "#mask-layer", "#tarteaucitronRoot", "[class*=cookie]",
    "[class*=breadcrumb]", "[class*=share]", "[class*=social]",
    "[class*=__icon]", "i.fa", "i.fal", "i.fas", "i.fab", "[aria-hidden=true]",
    "[class*=visually-hidden]", "[class*=sr-only]", "[class*=pagination]",
]

BLOCS = ["div", "section", "article", "p", "ul", "ol", "table", "tr",
         "dl", "dt", "dd", "blockquote", "figcaption", "aside", "details",
         "summary", "address"]
TITRES = ["h1", "h2", "h3", "h4", "h5", "h6"]

# Lignes sans information.
LIGNES_INUTILES = {
    "texte", "accueil", "lire la suite", "en savoir plus", "voir plus",
    "découvrir", "je candidate", "candidater", "télécharger", "contact",
    "retour", "partager", "suivant", "précédent", "fermer", "menu", "vide",
    "candidater télécharger nos brochures", "je candidate je m'inscris à la jpo",
    "télécharger nos brochures", "je m'inscris à la jpo",
}

LONGUEUR_MIN_PAGE = 120          # caractères : en dessous, page ignorée
PART_LIGNE_REPETEE = 0.35        # ligne sur > 35 % des pages = menu / bandeau

CATEGORIES_SLUG = [
    (r"^(bac|cycle|programme|licence|prepa|1ere|formation|bachelor|mastere|"
     r"safe|leading|agilite|msc|mba)", "formation"),
    (r"campus", "campus"),
    (r"admission|candidat|inscription|financ|cpf|bourse|aide|frais|vae", "admissions"),
    (r"entreprise|alternance|apprenti|taxe|recrut|stage|carriere", "entreprises"),
    (r"recherche|laboratoire|integrit", "recherche"),
]


# ------------------------------------------------------------------ URLS

def normaliser(url):
    """URL absolue, sans #ancre ni ?paramètres, sans / final."""
    p = urlparse(url)
    chemin = re.sub(r"/+$", "", p.path) or "/"
    return urlunparse(("https", p.netloc.lower(), chemin, "", "", ""))


def url_valide(url):
    p = urlparse(url)
    if p.netloc.lower() != urlparse(SITE).netloc:
        return False
    if not (p.path == PREFIXE or p.path.startswith(PREFIXE + "/")):
        return False
    chemin = p.path.lower()
    if chemin.endswith(EXTENSIONS_EXCLUES):
        return False
    if "@" in chemin:                 # adresse mail prise pour un lien
        return False
    return not any(x in chemin for x in CHEMINS_EXCLUS)


def urls_du_sitemap():
    try:
        r = requests.get(SITEMAP, timeout=20,
                         headers={"User-Agent": "PepperKnowledgeBot/1.0"})
        r.raise_for_status()
        racine = ET.fromstring(r.content)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [loc.text.strip() for loc in racine.findall(".//s:loc", ns)]
        print(f"Sitemap : {len(urls)} URLs")
        return urls
    except Exception as e:
        print(f"Sitemap indisponible ({e}), on part seulement de l'accueil.")
        return []


# -------------------------------------------------------------- NAVIGATEUR

def creer_navigateur(visible=False):
    from selenium import webdriver
    options = webdriver.ChromeOptions()
    if not visible:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=fr-FR")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    # Pas d'images : plus rapide, inutile pour le texte.
    options.add_experimental_option(
        "prefs", {"profile.managed_default_content_settings.images": 2})
    # Selenium Manager télécharge automatiquement le bon chromedriver.
    nav = webdriver.Chrome(options=options)
    nav.set_page_load_timeout(TIMEOUT_PAGE)
    return nav


def accepter_cookies(nav):
    """Ferme le bandeau cookies s'il existe."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    for xpath in [
        "//button[contains(@id,'AllowAll') or contains(@id,'accept')]",
        "//button[contains(translate(., 'ACEPTR', 'aceptr'), 'accepter')]",
    ]:
        try:
            for b in nav.find_elements(By.XPATH, xpath):
                if b.is_displayed():
                    b.click()
                    time.sleep(0.5)
                    return
        except WebDriverException:
            pass


def ouvrir(nav, url):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    nav.get(url)
    WebDriverWait(nav, TIMEOUT_PAGE).until(
        EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Défilement pour déclencher le contenu chargé à la demande.
    nav.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(0.6)
    # Ouvre accordéons / onglets / <details> (le texte est souvent déjà
    # dans le HTML, mais certains blocs ne se remplissent qu'à l'ouverture).
    nav.execute_script("""
        document.querySelectorAll('details').forEach(d => d.open = true);
        document.querySelectorAll('.collapse').forEach(c => c.classList.add('show'));
        document.querySelectorAll('[role=tabpanel], .tab-pane')
            .forEach(t => { t.classList.add('active', 'show'); t.hidden = false; });
    """)
    time.sleep(0.2)


def extraire_liens(nav):
    from selenium.common.exceptions import WebDriverException
    try:
        hrefs = nav.execute_script(
            "return Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => a.href);")
    except WebDriverException:
        return []
    return [normaliser(h) for h in hrefs if h and h.startswith("http")]


# ------------------------------------------------------------------ CACHE

def charger_index_cache():
    if INDEX_CACHE.exists():
        return json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
    return {}


def mettre_en_cache(index, url, html):
    CACHE.mkdir(parents=True, exist_ok=True)
    nom = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".html"
    (CACHE / nom).write_text(html, encoding="utf-8")
    index[url] = nom


def sauver_index_cache(index):
    CACHE.mkdir(parents=True, exist_ok=True)
    INDEX_CACHE.write_text(json.dumps(index, ensure_ascii=False, indent=0),
                           encoding="utf-8")


# -------------------------------------------------------------- EXTRACTION

def nettoyer(texte):
    """Espaces normalisés, emojis et caractères invisibles retirés."""
    texte = unicodedata.normalize("NFC", texte)
    texte = "".join(
        c for c in texte
        if unicodedata.category(c) not in ("So", "Cf", "Co", "Cs")
        and not 0xFE00 <= ord(c) <= 0xFE0F)
    texte = texte.replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", texte).strip()


def categorie_de(url, a_fiche):
    chemin = urlparse(url).path.lower()
    if "/actualites/" in chemin:
        return "actualite"
    if "/evenements/" in chemin:
        return "evenement"
    if a_fiche:
        return "formation"
    slug = chemin.rstrip("/").split("/")[-1]
    for motif, cat in CATEGORIES_SLUG:
        if re.search(motif, slug):
            return cat
    return "ecole"


def extraire_fiche(contenu):
    """Fiche résumée d'une formation : 'Durée : 2 ans', 'Coût : …'."""
    infos = []
    for item in contenu.select(".summary__item"):
        t = item.select_one("[class*=__title]")
        v = item.select_one("[class*=__content]")
        if t and v:
            titre = nettoyer(t.get_text(" "))
            valeur = re.sub(r"\s+", " ", nettoyer(v.get_text(" ")))
            if titre and valeur:
                infos.append(f"{titre} : {valeur}")
        item.decompose()
    return infos


def _coordonnees(bloc):
    """'Téléphone : …, Email : …' depuis des cartes .contact__item."""
    infos = []
    for item in bloc.select(".contact__item__content"):
        v = nettoyer(item.get_text(" "))
        if not v:
            continue
        if "@" in v:
            infos.append(f"Email : {v}")
        elif re.search(r"\d{2}[ .]?\d{2}", v):
            infos.append(f"Téléphone : {v}")
        else:
            infos.append(v)
    return ", ".join(infos)


def extraire_contacts(contenu):
    """Blocs de contact : onglets (noms) + panneaux (coordonnées)."""
    contacts = []
    for bloc in contenu.select(".content-block, .block-contact"):
        noms = [nettoyer(a.get_text(" ")) for a in bloc.select(".nav-tabs .nav-link")]
        panneaux = bloc.select(".tab-pane")
        if not panneaux or not bloc.select(".contact__item"):
            continue
        for i, pan in enumerate(panneaux):
            coord = _coordonnees(pan)
            nom = noms[i] if i < len(noms) else ""
            if coord:
                contacts.append(f"{nom} : {coord}" if nom else coord)
        bloc.decompose()
    # Cartes isolées.
    for item in contenu.select(".contact"):
        coord = _coordonnees(item)
        if coord:
            contacts.append(coord)
        item.decompose()
    return contacts


def extraire_page(html, url):
    soup = BeautifulSoup(html, "html.parser")

    titre_onglet = nettoyer(soup.title.get_text()) if soup.title else ""
    titre_onglet = re.sub(r"\s*[|\-–]\s*ESIEE[- ]?IT.*$", "", titre_onglet, flags=re.I)

    meta = soup.find("meta", attrs={"name": "description"}) \
        or soup.find("meta", attrs={"property": "og:description"})
    description = nettoyer(meta["content"]) if meta and meta.get("content") else ""
    description = re.sub(r"…$", "", description).strip()

    contenu = soup.select_one("main") or soup.select_one("article") or soup.body
    if contenu is None:
        return None

    h1 = contenu.find("h1") or soup.find("h1")
    titre = nettoyer(h1.get_text(" ")) if h1 else titre_onglet

    for sel in SELECTEURS_A_RETIRER:
        for el in contenu.select(sel):
            el.decompose()

    fiche = extraire_fiche(contenu)
    contacts = extraire_contacts(contenu)

    # Chiffres clés : « 93.5 » + « % » + libellé sont dans des blocs séparés.
    # Le bloc reçoit un titre « Chiffres clés » pour être retrouvé facilement.
    for groupe in contenu.select(".key-figures"):
        titre_cc = soup.new_tag("h2")
        titre_cc.string = "Chiffres clés d'ESIEE-IT"
        groupe.insert_before(titre_cc)
    for kf in contenu.select(".key-figure"):
        bloc = kf.parent
        valeur = nettoyer(kf.get_text(""))
        kf.decompose()
        libelle = nettoyer(bloc.get_text(" "))
        bloc.clear()
        nouveau = soup.new_tag("p")
        nouveau.string = f"{valeur} {libelle}".strip()
        bloc.append(nouveau)

    # Boutons : on garde le texte des titres d'accordéon (dans un <hN>),
    # on supprime les autres (« Je candidate », « Fermer »…).
    for b in contenu.find_all(["button", "a"]):
        if b.name == "button" and not b.find_parent(TITRES):
            b.decompose()
        else:
            b.unwrap()

    # Les retours à la ligne du code HTML ne veulent rien dire : on les
    # remplace par des espaces, puis on ajoute nos propres marqueurs.
    for s in list(contenu.find_all(string=True)):
        if not isinstance(s, NavigableString) or s.parent is None:
            continue
        s.replace_with(NavigableString(re.sub(r"\s+", " ", str(s))))

    # Marqueurs de structure, puis texte brut découpé en lignes.
    for br in contenu.find_all("br"):
        br.replace_with("\n")
    for el in contenu.find_all(TITRES):
        el.insert(0, NavigableString("\n## "))
        el.append(NavigableString("\n"))
    for el in contenu.find_all("li"):
        el.insert(0, NavigableString("\n- "))
        el.append(NavigableString("\n"))
    for el in contenu.find_all(["td", "th"]):
        el.append(NavigableString(" | "))
    for el in contenu.find_all(BLOCS):
        el.insert(0, NavigableString("\n"))
        el.append(NavigableString("\n"))

    lignes = []
    for brut in contenu.get_text("").split("\n"):
        l = nettoyer(brut)
        l = re.sub(r"(\s*\|\s*)+$", "", l)          # « | » final des tableaux
        l = re.sub(r"^(- |## )?[?\s]+(?=\S)", r"\1", l)   # emojis abîmés « ? »
        l = re.sub(r"^(- |## )\s*", r"\1", l)
        if l in ("", "-", "##", "|"):
            continue
        cle = re.sub(r"^(- |## )", "", l).strip(" :.").lower()
        if cle in LIGNES_INUTILES or len(cle) < 2:
            continue
        # Doublon de la ligne précédente (ex. h1 répété, « ## » + même texte).
        if lignes and re.sub(r"^(- |## )", "", lignes[-1]) == re.sub(r"^(- |## )", "", l):
            continue
        lignes.append(l)

    # Un titre suivi directement d'un autre titre sans contenu = titre vide.
    propres = []
    for i, l in enumerate(lignes):
        suivant = lignes[i + 1] if i + 1 < len(lignes) else "## "
        if l.startswith("## ") and suivant.startswith("## ") and \
                l[3:].lower() in ("objectifs", "programme", "texte"):
            continue
        propres.append(l)

    return {
        "url": url,
        "titre": titre or titre_onglet or url,
        "description": description,
        "categorie": categorie_de(url, bool(fiche)),
        "fiche": fiche,
        "contacts": contacts,
        "lignes": propres,
    }


# ---------------------------------------------------------- POST-TRAITEMENT

def finaliser(pages):
    """Retire les lignes répétées partout (menus) et les pages en double."""
    compte = Counter()
    for p in pages:
        compte.update(set(p["lignes"]))
    seuil = max(5, int(PART_LIGNE_REPETEE * len(pages)))
    communes = {l for l, n in compte.items() if n >= seuil}
    print(f"Lignes répétées retirées (menus, bandeaux) : {len(communes)}")

    documents, empreintes, titres_vus = [], set(), Counter()
    annuaire = []
    for p in pages:
        lignes = [l for l in p["lignes"] if l not in communes]
        # Le titre de la page est déjà dans le champ « titre ».
        lignes = [l for l in lignes
                  if re.sub(r"^(## |- )", "", l) != p["titre"]]

        # Fiche d'une personne (nom + coordonnées) -> annuaire commun.
        if p.get("contacts") and len("\n".join(lignes)) < LONGUEUR_MIN_PAGE:
            for c in p["contacts"]:
                ligne = c if c.startswith(p["titre"]) else f"{p['titre']} : {c}"
                if ligne not in annuaire:
                    annuaire.append(ligne)
            continue
        if p.get("contacts"):
            lignes.append("## Contacts\n" +
                          "\n".join("- " + c for c in p["contacts"]))

        parties = []
        corps = "\n".join(lignes)
        if p["description"] and p["description"][:60] not in corps:
            parties.append(p["description"])
        if p["fiche"]:
            parties.append("## Informations clés\n" +
                           "\n".join("- " + x for x in p["fiche"]))
        parties.append(corps)
        contenu = "\n".join(x for x in parties if x).strip()

        if len(contenu) < LONGUEUR_MIN_PAGE:
            continue
        empreinte = hashlib.sha256(contenu.encode("utf-8")).hexdigest()
        if empreinte in empreintes:
            continue
        empreintes.add(empreinte)

        titre = p["titre"]
        titres_vus[titre] += 1
        if titres_vus[titre] > 1:               # titres identiques : on les distingue
            titre = f"{titre} ({titres_vus[titre]})"
        documents.append({
            "titre": titre,
            "categorie": p["categorie"],
            "contenu": contenu,
        })

    if annuaire:
        documents.append({
            "titre": "Annuaire des contacts ESIEE-IT",
            "categorie": "contacts",
            "contenu": "Coordonnées des membres de l'équipe ESIEE-IT "
                       "(téléphone et email) :\n" +
                       "\n".join("- " + a for a in sorted(annuaire)),
        })

    ordre = ["ecole", "formation", "admissions", "campus", "contacts", "entreprises",
             "recherche", "evenement", "actualite"]
    documents.sort(key=lambda d: ordre.index(d["categorie"])
                   if d["categorie"] in ordre else len(ordre))
    return documents


def ecrire_sortie(pages):
    documents = finaliser(pages)
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)
    total = sum(len(d["contenu"]) for d in documents)
    cats = Counter(d["categorie"] for d in documents)
    print(f"\n{len(documents)} documents ({total:,} caractères) -> {SORTIE}")
    print("Par catégorie :", dict(cats.most_common()))


def sauver_etat(file, vus, faites):
    with open(ETAT, "w", encoding="utf-8") as f:
        json.dump({"file": list(file), "vus": sorted(vus), "faites": faites},
                  f, ensure_ascii=False)


# ------------------------------------------------------------------- MAIN

def depuis_cache():
    index = charger_index_cache()
    if not index:
        print("Cache vide : lancez d'abord le scraping.")
        return
    pages = []
    for url, nom in index.items():
        if urlparse(url).path in PAGES_LISTES or not url_valide(url):
            continue
        chemin = CACHE / nom
        if chemin.exists():
            page = extraire_page(chemin.read_text(encoding="utf-8"), url)
            if page and (page["lignes"] or page["contacts"]):
                pages.append(page)
    print(f"{len(pages)} pages relues depuis le cache")
    ecrire_sortie(pages)


def crawler(args):
    from selenium.common.exceptions import TimeoutException, WebDriverException

    DATA_DIR.mkdir(exist_ok=True)
    index = charger_index_cache() if args.reprendre else {}

    if args.reprendre and ETAT.exists():
        etat = json.loads(ETAT.read_text(encoding="utf-8"))
        file, vus, faites = deque(etat["file"]), set(etat["vus"]), etat["faites"]
        print(f"Reprise : {len(faites)} pages déjà faites, {len(file)} en attente")
    else:
        if CACHE.exists():
            shutil.rmtree(CACHE)
        depart = [DEPART] + ([] if args.sans_sitemap else urls_du_sitemap())
        # Pages de fond (programmes, école…) d'abord, actualités ensuite.
        secondaires = ("/fr/actualites/", "/fr/evenements/")
        depart.sort(key=lambda u: any(s in u for s in secondaires))
        file, vus, faites = deque(), set(), []
        for u in depart:
            u = normaliser(u)
            if url_valide(u) and u not in vus:
                vus.add(u)
                file.append(u)

    nav = creer_navigateur(args.visible)
    erreurs, debut, premiere = 0, time.time(), True
    try:
        while file and len(faites) < args.max_pages:
            url = file.popleft()
            print(f"[{len(faites) + 1:4d} | file {len(file):4d}] {url}")
            try:
                ouvrir(nav, url)
                if premiere:
                    accepter_cookies(nav)
                    premiere = False
                url_finale = normaliser(nav.current_url)
                if not url_valide(url_finale) or (url_finale != url and url_finale in index):
                    continue           # redirection hors site ou déjà faite
                vus.add(url_finale)
                for lien in extraire_liens(nav):
                    if lien not in vus and url_valide(lien):
                        vus.add(lien)
                        file.append(lien)
                mettre_en_cache(index, url_finale, nav.page_source)
                faites.append(url_finale)
            except (TimeoutException, WebDriverException) as e:
                erreurs += 1
                print(f"   ! erreur : {str(e).splitlines()[0][:120]}")
                if erreurs > 20 and erreurs > len(faites):
                    print("Trop d'erreurs, arrêt.")
                    break
            if len(faites) % 10 == 0:
                sauver_etat(file, vus, faites)
                sauver_index_cache(index)
            time.sleep(DELAI)
    except KeyboardInterrupt:
        print("\nInterrompu : relancer avec --reprendre pour continuer.")
    finally:
        sauver_etat(file, vus, faites)
        sauver_index_cache(index)
        nav.quit()

    print(f"Pages téléchargées : {len(faites)}, erreurs : {erreurs}, "
          f"durée : {(time.time() - debut) / 60:.1f} min")
    if not file:
        ETAT.unlink(missing_ok=True)
    depuis_cache()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--visible", action="store_true", help="afficher Chrome")
    ap.add_argument("--reprendre", action="store_true",
                    help="reprendre un scraping interrompu")
    ap.add_argument("--sans-sitemap", action="store_true",
                    help="suivre uniquement les liens depuis l'accueil")
    ap.add_argument("--depuis-cache", action="store_true",
                    help="ré-extraire le texte du cache, sans navigateur")
    args = ap.parse_args()
    if args.depuis_cache:
        depuis_cache()
    else:
        crawler(args)


if __name__ == "__main__":
    main()
