"""Outils partagés par la chaîne RAG (chemins, normalisation du texte)."""

import re
import unicodedata
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
DATA_DIR = RAG_DIR / "data"
CACHE_DIR = DATA_DIR / "html_cache"
KB_DIR = DATA_DIR / "kb"                       # base de connaissances nettoyée
EVAL_DIR = RAG_DIR / "eval"

DOCUMENTS_NETTOYES = KB_DIR / "documents_nettoyes.json"
CHUNKS = KB_DIR / "chunks.json"
STATS_NETTOYAGE = KB_DIR / "stats_nettoyage.json"
STATS_CHUNKS = KB_DIR / "stats_chunks.json"
QUESTIONS = EVAL_DIR / "questions.json"
RESULTATS_EVAL = KB_DIR / "evaluation.json"
CHROMA_DIR = DATA_DIR / "chroma_db"

OLLAMA_URL = "http://127.0.0.1:11434"
MODELE_EMBEDDING = "embeddinggemma"
COLLECTION = "esiee_it_kb"

SOURCE = "Site officiel ESIEE-IT (www.esiee-it.fr)"

MOTS_VIDES = set("""
a à au aux avec ce ces cet cette ci comme dans de des du elle elles en entre et
est être été eux il ils je la le les leur leurs lui ma mais me même mes moi mon
ne nos notre nous on ou où par pas pour qu que qui sa se ses si son sont sur ta
te tes toi ton tu un une vos votre vous y d l n s t c j m qu' plus moins très
tout tous toute toutes aussi ainsi alors avoir fait faire peut peuvent sera
seront sans sous chez dont cela celle celles celui ceux ici là quel quelle
quels quelles quoi comment combien pourquoi quand est-ce estce ont avez avons
suis es sommes êtes etc afin selon lors après avant depuis pendant vers via
votre vos leurs chaque autre autres bien encore déjà non oui faut existe
the and of to in for is on with are by an be
""".split())


def sans_accents(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn")


MOTS_VIDES = {sans_accents(m) for m in MOTS_VIDES}


def normaliser_texte(texte):
    """Minuscules, sans accents, espaces simples (pour comparer)."""
    texte = sans_accents(texte.lower())
    texte = re.sub(r"[’'`]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def racine(mot):
    """Racinisation très légère (pluriels) : formations -> formation."""
    if len(mot) > 4 and mot.endswith(("s", "x")) and not mot.endswith("ss"):
        return mot[:-1]
    return mot


def tokens(texte, garder_vides=False):
    mots = re.findall(r"[a-z0-9+#]+", normaliser_texte(texte))
    if not garder_vides:
        mots = [m for m in mots if m not in MOTS_VIDES and len(m) > 1]
    return [racine(m) for m in mots]
