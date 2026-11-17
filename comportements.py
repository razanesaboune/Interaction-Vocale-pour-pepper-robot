"""
Comportements non verbaux de Pepper (NAOqi 2.5).

1. Détection et suivi de l'interlocuteur (ALBasicAwareness)
   Pepper repère les visages et garde la tête tournée vers la
   personne avec qui il parle. Il peut saluer une nouvelle personne.

2. Localisation de la source sonore (ALSoundLocalization)
   Quand notre détecteur de voix se déclenche, Pepper tourne la tête
   vers l'endroit d'où vient la voix (utile si personne n'est encore
   suivi, par exemple quelqu'un qui parle à côté de lui).
   On n'utilise PAS le stimulus « Sound » d'ALBasicAwareness, qui
   réagirait à n'importe quel bruit : seule une voix validée par
   detection_parole.py fait tourner la tête.

3. Gestes adaptés au contenu de la réponse
   Le texte de la réponse est analysé (mots-clés français) pour
   choisir une animation cohérente : salut, oui, non, je ne sais pas,
   remerciement, enthousiasme, explication... Le geste est lancé en
   même temps que la parole.

4. Voix
   - « pepper_claire » : voix intégrée de Pepper, réglée pour être
     plus naturelle et plus claire (moins aiguë, un peu plus lente).
   - « piper » : voix neuronale française fr_FR-siwis (très claire),
     générée sur le PC puis jouée par les haut-parleurs de Pepper.
     Nécessite : pip install piper-tts
"""

import os
import random
import re
import time
import unicodedata
import wave


# ==========================================
# PARAMÈTRES
# ==========================================

# Voix : "pepper_claire", "pepper_origine" ou "piper".
VOIX = "pepper_claire"

# Réglages de la voix intégrée de Pepper (mode "pepper_claire").
# pitchShift : 1.0 = voix naturelle (Pepper est réglé à 1.28 : aiguë).
VOIX_PEPPER_HAUTEUR = 1.0
VOIX_PEPPER_VITESSE = 90       # % (100 = normal)
VOIX_PEPPER_VOLUME = 0.8       # 0 à 1

# Voix Piper.
MODELE_PIPER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fr_FR-siwis-medium.onnx")
FICHIER_PIPER_LOCAL = "/tmp/pepper_reponse.wav"
FICHIER_PIPER_ROBOT = "/home/nao/pepper_reponse.wav"

# Suivi de l'interlocuteur.
#   "Head"         : seule la tête suit la personne (le plus sûr) ;
#   "BodyRotation" : Pepper tourne aussi sa base sur place.
MODE_SUIVI = "Head"

# « FullyEngaged » : reste concentré sur la personne suivie.
MODE_ENGAGEMENT = "FullyEngaged"

# Saluer une personne qui arrive devant Pepper.
SALUER_NOUVELLE_PERSONNE = True
DELAI_ENTRE_SALUTS = 30.0      # secondes
PHRASE_SALUT = "Bonjour ! Je suis Pepper. Vous pouvez me parler."

# Localisation sonore : confiance minimale et limites de la tête.
CONFIANCE_SON_MIN = 0.3
LIMITE_LACET = 1.8             # rad (gauche/droite)
LIMITE_TANGAGE = (-0.4, 0.3)   # rad (haut/bas)
VITESSE_TETE = 0.15

# Gestes.
GESTES_ACTIFS = True
GESTE_PAR_DEFAUT_MIN_MOTS = 6  # pas de geste sur les réponses très courtes


# ==========================================
# CHOIX DES GESTES
# ==========================================

G = "animations/Stand/Gestures/"
E = "animations/Stand/Emotions/"

# (motif sur le texte sans accents, animations possibles).
# La PREMIÈRE règle qui correspond est utilisée.
REGLES_GESTES = [
    (r"\b(bonjour|salut|coucou|bonsoir|enchante)\b",
     [G + "Hey_1", G + "Hey_6"]),
    (r"\b(au revoir|a bientot|a plus tard|bonne journee|bonne soiree)\b",
     [G + "Hey_3", G + "Hey_4"]),
    (r"\b(merci)\b",
     [G + "BowShort_1", G + "BowShort_2"]),
    (r"\b(je ne sais pas|je ne suis pas sur|aucune idee)\b",
     [G + "IDontKnow_1", G + "IDontKnow_2"]),
    (r"\b(desole|pardon|excuse)\b",
     [E + "Negative/Sorry_1"]),
    (r"\b(je ne comprends pas|pas compris|repeter)\b",
     [G + "DontUnderstand_1", G + "Confused_1"]),
    (r"^(non|pas du tout|jamais)\b",
     [G + "No_3", G + "No_8", G + "No_9"]),
    (r"^(oui|bien sur|d'accord|exactement|absolument|tout a fait)\b",
     [G + "Yes_1", G + "Yes_2", G + "Yes_3"]),
    (r"\b(super|genial|bravo|excellent|felicitations|formidable)\b",
     [G + "Enthusiastic_4", G + "Enthusiastic_5", G + "Great_1"]),
    (r"\b(peut-etre|probablement|il se peut)\b",
     [G + "Maybe_1"]),
    (r"\b(le ciel|en haut|les etoiles|l'espace)\b",
     [G + "ShowSky_1", G + "ShowSky_2"]),
    (r"\b(loin|lointain)\b",
     [G + "Far_1", G + "Far_2"]),
    (r"^(je suis|moi)\b",
     [G + "Me_1", G + "Me_2"]),
    (r"^(vous|tu)\b",
     [G + "You_1", G + "You_2"]),
    (r"\b(d'abord|premierement|ensuite|enfin|par exemple)\b",
     [G + "Explain_1", G + "Explain_2", G + "Explain_3"]),
]

GESTES_EXPLICATION = [G + "Explain_{}".format(i) for i in (1, 2, 3, 4, 5, 6, 7, 8)]


def sans_accents(texte):
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def choisir_geste(texte):
    """Retourne le chemin d'une animation adaptée au texte, ou None."""

    if not GESTES_ACTIFS:
        return None

    t = sans_accents(texte).strip()

    for motif, animations in REGLES_GESTES:
        if re.search(motif, t):
            return random.choice(animations)

    # Geste d'explication neutre pour les réponses assez longues.
    if len(t.split()) >= GESTE_PAR_DEFAUT_MIN_MOTS:
        return random.choice(GESTES_EXPLICATION)

    return None


# ==========================================
# CLASSE PRINCIPALE
# ==========================================

class Comportements(object):

    def __init__(self, session, ip_robot, nom="PepperAutonome"):
        self.session = session
        self.ip_robot = ip_robot
        self.nom = nom

        self.tts = session.service("ALTextToSpeech")
        self.animated_speech = session.service("ALAnimatedSpeech")
        self.animation_player = session.service("ALAnimationPlayer")
        self.memory = session.service("ALMemory")
        self.motion = session.service("ALMotion")
        self.awareness = session.service("ALBasicAwareness")
        self.son_loc = session.service("ALSoundLocalization")

        self.dernier_son = None
        self.derniere_personne = -1
        self.dernier_salut = 0.0
        self.voix_piper = None

    # ------------------------------------------
    # DÉMARRAGE / ARRÊT
    # ------------------------------------------

    def demarrer(self):
        self._configurer_voix()
        self._demarrer_suivi()
        self._demarrer_localisation()

    def arreter(self):
        try:
            self.awareness.stopAwareness()
        except Exception:
            pass
        try:
            self.son_loc.unsubscribe(self.nom)
        except Exception:
            pass
        # Remettre la voix d'origine de Pepper.
        if VOIX != "pepper_origine":
            try:
                self.tts.resetSpeed()
                self.tts.setParameter("pitchShift", 1.28)
            except Exception:
                pass

    # ------------------------------------------
    # 1. SUIVI DE L'INTERLOCUTEUR
    # ------------------------------------------

    def _demarrer_suivi(self):
        try:
            a = self.awareness
            # On suit les personnes ; le son est géré par nous
            # (seulement une vraie voix), le mouvement est ignoré
            # pour éviter que Pepper tourne la tête au moindre passage.
            a.setStimulusDetectionEnabled("People", True)
            a.setStimulusDetectionEnabled("Touch", True)
            a.setStimulusDetectionEnabled("Sound", False)
            a.setStimulusDetectionEnabled("Movement", False)
            a.setEngagementMode(MODE_ENGAGEMENT)
            a.setTrackingMode(MODE_SUIVI)
            a.startAwareness()
            print("Suivi de l'interlocuteur activé ({}, {}).".format(
                MODE_ENGAGEMENT, MODE_SUIVI))
        except Exception as e:
            print("Erreur suivi interlocuteur :", e)

    def personne_suivie(self):
        """Identifiant de la personne suivie, ou -1."""
        try:
            valeur = self.memory.getData("ALBasicAwareness/HumanTracked")
            return int(valeur) if valeur is not None else -1
        except Exception:
            return -1

    def nouvelle_personne_a_saluer(self):
        """True si une nouvelle personne vient d'être repérée."""

        if not SALUER_NOUVELLE_PERSONNE:
            return False

        pid = self.personne_suivie()
        nouvelle = (pid >= 0 and pid != self.derniere_personne)
        self.derniere_personne = pid

        if nouvelle and time.time() - self.dernier_salut > DELAI_ENTRE_SALUTS:
            self.dernier_salut = time.time()
            return True

        return False

    # ------------------------------------------
    # 2. LOCALISATION DE LA SOURCE SONORE
    # ------------------------------------------

    def _demarrer_localisation(self):
        try:
            self.son_loc.subscribe(self.nom)
            self.dernier_son = self._lire_son()
            print("Localisation sonore activée.")
        except Exception as e:
            print("Erreur localisation sonore :", e)

    def _lire_son(self):
        try:
            return self.memory.getData("ALSoundLocalization/SoundLocated")
        except Exception:
            return None

    def regarder_source_sonore(self):
        """
        Tourne la tête vers la dernière source sonore localisée.
        À appeler quand une voix vient d'être détectée.
        Retourne l'angle (degrés, + = gauche) ou None.
        """

        donnees = self._lire_son()

        # Format NAOqi 2.5 :
        # [[sec, usec], [azimut, élévation, confiance, énergie],
        #  [position tête / torse (x, y, z, wx, wy, wz)], [...]]
        if not donnees or donnees == self.dernier_son:
            return None
        self.dernier_son = donnees

        try:
            azimut, elevation, confiance, _ = donnees[1]
            tete = donnees[2]
        except Exception:
            return None

        if confiance < CONFIANCE_SON_MIN:
            return None

        # Si une personne est déjà suivie, le suivi s'occupe de la tête.
        if self.personne_suivie() >= 0:
            return None

        # Angles mesurés par rapport à la tête au moment du son.
        lacet = max(-LIMITE_LACET, min(LIMITE_LACET, tete[5] + azimut))
        tangage = max(LIMITE_TANGAGE[0], min(LIMITE_TANGAGE[1], tete[4] - elevation))

        try:
            self.motion.setAngles(["HeadYaw", "HeadPitch"],
                                  [lacet, tangage], VITESSE_TETE)
        except Exception as e:
            print("Erreur mouvement tête :", e)
            return None

        return round(lacet * 57.3)

    # ------------------------------------------
    # 3 + 4. PAROLE AVEC GESTES
    # ------------------------------------------

    def _configurer_voix(self):
        global VOIX

        if VOIX == "piper":
            try:
                from piper import PiperVoice
                self.voix_piper = PiperVoice.load(MODELE_PIPER)
                self.audio_player = self.session.service("ALAudioPlayer")
                print("Voix Piper (fr_FR-siwis) chargée.")
                return
            except Exception as e:
                print("Voix Piper indisponible ({}) : voix de Pepper "
                      "réglée à la place.".format(e))
                VOIX = "pepper_claire"

        if VOIX == "pepper_claire":
            try:
                self.tts.setParameter("pitchShift", VOIX_PEPPER_HAUTEUR)
                self.tts.setParameter("speed", VOIX_PEPPER_VITESSE)
                self.tts.setParameter("doubleVoice", 0.0)
                self.tts.setVolume(VOIX_PEPPER_VOLUME)
                print("Voix de Pepper réglée (hauteur {}, vitesse {} %).".format(
                    VOIX_PEPPER_HAUTEUR, VOIX_PEPPER_VITESSE))
            except Exception as e:
                print("Erreur réglage voix :", e)

    def parler(self, texte):
        """Prononce le texte avec un geste adapté (bloquant)."""

        geste = choisir_geste(texte)
        if geste:
            print("Geste :", geste.split("/")[-1])

        if self.voix_piper is not None:
            self._parler_piper(texte, geste)
            return

        if geste:
            # Le geste démarre avec la phrase ; on attend sa fin
            # avant de rendre la main.
            texte_anime = "^start({0}) {1} ^wait({0})".format(geste, texte)
        else:
            texte_anime = texte

        try:
            self.animated_speech.say(texte_anime,
                                     {"bodyLanguageMode": "contextual"})
        except Exception as e:
            print("Erreur parole animée ({}), parole simple.".format(e))
            self.tts.say(texte)

    def _parler_piper(self, texte, geste):
        import paramiko

        # 1. Synthèse sur le PC.
        with wave.open(FICHIER_PIPER_LOCAL, "wb") as f:
            if hasattr(self.voix_piper, "synthesize_wav"):
                self.voix_piper.synthesize_wav(texte, f)      # piper-tts >= 1.3
            else:
                self.voix_piper.synthesize(texte, f)          # piper-tts 1.2

        # 2. Envoi sur Pepper.
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.ip_robot, username="nao", timeout=10)
            sftp = ssh.open_sftp()
            try:
                sftp.put(FICHIER_PIPER_LOCAL, FICHIER_PIPER_ROBOT)
            finally:
                sftp.close()
        finally:
            ssh.close()

        # 3. Geste + lecture en même temps.
        if geste:
            try:
                self.animation_player.run(geste, _async=True)
            except Exception:
                pass

        self.audio_player.playFile(FICHIER_PIPER_ROBOT)
