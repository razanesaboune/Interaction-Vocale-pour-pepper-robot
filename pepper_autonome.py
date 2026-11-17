"""
Pepper en conversation AUTONOME (sans toucher la tête).

Pepper écoute en permanence le micro avant (flux audio en direct).
Dès qu'une voix dépasse le seuil adaptatif au-dessus du bruit ambiant,
il commence à enregistrer ; quand la personne se tait, il transcrit
(Whisper), demande une réponse (Ollama) et la prononce.
Le bruit normal (ventilateur, salle, claquements, voix lointaines)
est ignoré : voir detection_parole.py.

Pendant que Pepper réfléchit et parle, le micro est coupé
(il ne s'entend pas lui-même).

PRÉREQUIS RÉSEAU : Pepper doit pouvoir se connecter à ce script pour
lui envoyer le son. Sous WSL, il faut le mode réseau « mirrored »
(voir le message affiché en cas d'échec).
"""

import io
import queue
import socket
import time
import wave

import numpy as np
import qi
import requests

from comportements import Comportements, PHRASE_SALUT
from detection_parole import DetecteurParole, EcouteContinue


# ==========================================
# 1. CONFIGURATION
# ==========================================

ROBOT_IP = "169.254.9.153"
ROBOT_PORT = 9559

# Port sur lequel Pepper se connecte à ce script pour envoyer le son
# (doit être autorisé dans le pare-feu Hyper-V de WSL).
PORT_ECOUTE = 9600

OLLAMA_MODEL = "llama3.2:3b"

FREQUENCE = 16000

# Mesure du bruit ambiant au démarrage (ne pas parler).
CALIBRATION_SECONDS = 3

# Pause après que Pepper a parlé, avant de réécouter
# (évite d'entendre la fin de sa propre voix).
PAUSE_APRES_PAROLE = 0.7

NOM_SERVICE_MICRO = "MicroPepperAutonome"

MOTS_ARRET = [
    "stop",
    "arrête",
    "arrête-toi",
    "arrête toi",
    "quitte",
    "au revoir",
]


def trouver_windows_ip():
    """
    Adresse des services Windows (Whisper, Ollama) vue depuis WSL :
    - mode « mirrored » : localhost fonctionne ;
    - mode NAT : c'est la passerelle par défaut de WSL.
    """

    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=0.5):
            return "127.0.0.1"
    except OSError:
        pass

    try:
        with open("/proc/net/route") as f:
            for ligne in f.readlines()[1:]:
                champs = ligne.split()
                if champs[1] == "00000000":
                    passerelle = int(champs[2], 16)
                    return socket.inet_ntoa(passerelle.to_bytes(4, "little"))
    except Exception:
        pass

    return "127.0.0.1"


WINDOWS_IP = trouver_windows_ip()
WHISPER_URL = "http://{}:5000/transcribe".format(WINDOWS_IP)
OLLAMA_URL = "http://{}:11434/api/chat".format(WINDOWS_IP)


# ==========================================
# 2. CONNEXION À PEPPER
# ==========================================

print("Connexion à Pepper...")

session = qi.Session()

try:
    session.connect("tcp://{}:{}".format(ROBOT_IP, ROBOT_PORT))

    # Indispensable pour que Pepper puisse appeler notre service
    # micro (il se connecte à nous pour envoyer le son).
    session.listen("tcp://0.0.0.0:{}".format(PORT_ECOUTE))

    print("Connecté à Pepper !")

except Exception as e:
    print("Erreur connexion Pepper :", e)
    raise SystemExit(1)

tts = session.service("ALTextToSpeech")
audio_device = session.service("ALAudioDevice")
leds = session.service("ALLeds")

tts.setVolume(0.6)


# ==========================================
# 2 bis. COULEURS DES YEUX ET DES OREILLES
# ==========================================
# Yeux : couleur RGB. Oreilles : LED bleues uniquement,
# on ne peut régler que leur intensité (0 à 1).

MODES_LEDS = {
    #  mode         couleur yeux  intensité oreilles
    "attente":    (0xFFFFFF, 0.2),   # blanc, oreilles faibles
    "ecoute":     (0x00FF00, 1.0),   # vert, oreilles allumées
    "reflexion":  (0xFF8C00, 0.5),   # orange
    "parole":     (0x0050FF, 0.0),   # bleu, oreilles éteintes
}

DUREE_TRANSITION_LEDS = 0.2

mode_leds_actuel = None


def changer_mode(mode):
    """Change la couleur des yeux et l'intensité des oreilles."""

    global mode_leds_actuel

    if mode == mode_leds_actuel:
        return

    couleur, intensite_oreilles = MODES_LEDS[mode]

    try:
        # _async=True : ne bloque pas l'écoute pendant la transition.
        leds.fadeRGB("FaceLeds", couleur, DUREE_TRANSITION_LEDS, _async=True)
        leds.fade("EarLeds", intensite_oreilles, DUREE_TRANSITION_LEDS, _async=True)
        mode_leds_actuel = mode
    except Exception as e:
        print("Erreur LEDs :", e)


def remettre_leds():
    """Couleurs par défaut de Pepper à la fin du programme."""
    try:
        leds.fadeRGB("FaceLeds", 0xFFFFFF, 0.3)
        leds.fade("EarLeds", 1.0, 0.3)
    except Exception:
        pass


# ==========================================
# 3. CONFIGURATION DE PEPPER
# ==========================================

def configurer_pepper():

    print("\nConfiguration de Pepper...")

    try:
        life = session.service("ALAutonomousLife")
        if life.getState() != "disabled":
            life.setState("disabled")
        print("Vie autonome désactivée.")
    except Exception as e:
        print("Erreur vie autonome :", e)

    try:
        session.service("ALBasicAwareness").stopAwareness()
        print("Suivi automatique désactivé.")
    except Exception as e:
        print("Erreur awareness :", e)

    try:
        session.service("ALAnimatedSpeech").setBodyLanguageMode(0)
        print("Gestes de parole désactivés.")
    except Exception as e:
        print("Erreur gestes :", e)

    try:
        motion = session.service("ALMotion")
        # Désactiver la vie autonome peut mettre Pepper au repos.
        motion.wakeUp()
        motion.setBreathEnabled("Body", False)
        print("Mouvements de respiration désactivés.")
    except Exception as e:
        print("Erreur respiration :", e)

    try:
        posture = session.service("ALRobotPosture")
        if posture.getPosture() != "Stand":
            posture.goToPosture("Stand", 0.3)
        print("Posture debout demandée.")
    except Exception as e:
        print("Erreur posture :", e)

    try:
        tts.stopAll()
    except Exception:
        pass

    print("Pepper configuré : debout et silencieux.")


# ==========================================
# 4. FLUX AUDIO EN DIRECT DU MICRO
# ==========================================

class MicroPepper(object):
    """
    Service appelé par ALAudioDevice environ 12 fois par seconde
    avec le son du micro avant. Il doit répondre très vite :
    il se contente de mettre le son dans une file d'attente.
    """

    def __init__(self):
        self.file = queue.Queue(maxsize=1000)
        self.actif = False

    def processRemote(self, nbOfChannels, nbOfSamplesByChannel,
                      timeStamp, inputBuffer):
        if not self.actif:
            return
        try:
            self.file.put_nowait(bytes(inputBuffer))
        except queue.Full:
            pass

    # -- utilitaires (non appelés par Pepper) --

    def _vider(self):
        while True:
            try:
                self.file.get_nowait()
            except queue.Empty:
                return

    def couper(self):
        self.actif = False
        self._vider()

    def ouvrir(self):
        self._vider()
        self.actif = True

    def lire(self, timeout=1.0):
        """Retourne un morceau de son (float32) ou None."""
        try:
            brut = self.file.get(timeout=timeout)
        except queue.Empty:
            return None
        return np.frombuffer(brut, dtype="<i2").astype(np.float32) / 32768.0


micro = MicroPepper()
id_service_micro = None


def demarrer_micro():
    global id_service_micro

    # Nettoyer un éventuel abonnement laissé par un arrêt brutal.
    try:
        audio_device.unsubscribe(NOM_SERVICE_MICRO)
    except Exception:
        pass

    id_service_micro = session.registerService(NOM_SERVICE_MICRO, micro)

    # 16 kHz, canal 3 = micro avant, données non entrelacées.
    audio_device.setClientPreferences(NOM_SERVICE_MICRO, FREQUENCE, 3, 0)
    audio_device.subscribe(NOM_SERVICE_MICRO)


def arreter_micro():
    micro.couper()
    try:
        audio_device.unsubscribe(NOM_SERVICE_MICRO)
    except Exception:
        pass
    if id_service_micro is not None:
        try:
            session.unregisterService(id_service_micro)
        except Exception:
            pass


# ==========================================
# 5. WHISPER, OLLAMA, PAROLE
# ==========================================

messages = [
    {
        "role": "system",
        "content": (
            "Tu es Pepper, un robot humanoïde assistant. "
            "Tu parles avec un utilisateur en face de toi. "
            "Réponds dans la même langue que l'utilisateur. "
            "Réponds brièvement, naturellement et clairement. "
            "Privilégie une ou deux phrases faciles à prononcer. "
            "Ne décris pas de gestes et n'ajoute pas "
            "d'indications scéniques. "
            "Si la question est incompréhensible, "
            "demande poliment de la répéter."
        )
    }
]


def signal_vers_wav(signal):
    """Convertit un signal float32 en fichier WAV (en mémoire)."""

    tampon = io.BytesIO()
    donnees = (np.clip(signal, -1, 1) * 32767).astype("<i2")

    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(FREQUENCE)
        f.writeframes(donnees.tobytes())

    return tampon.getvalue()


def transcrire(signal):
    response = requests.post(
        WHISPER_URL,
        files={"audio": ("question.wav", signal_vers_wav(signal), "audio/wav")},
        timeout=120
    )
    response.raise_for_status()
    return response.json().get("text", "").strip()


def demander_ollama(question):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": messages + [{"role": "user", "content": question}],
            "stream": False
        },
        timeout=120
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def verifier_service(nom, url):
    try:
        requests.get(url, timeout=5).raise_for_status()
        print("{} accessible ({})".format(nom, url))
    except Exception as e:
        print("ATTENTION : {} inaccessible : {}".format(nom, e))


# ==========================================
# 6. TRAITEMENT D'UNE PRISE DE PAROLE
# ==========================================

def traiter(signal):
    """
    Retourne False si l'utilisateur a demandé d'arrêter.
    """

    global messages

    print("Transcription avec Whisper...")
    t0 = time.time()

    try:
        question = transcrire(signal)
    except Exception as e:
        print("Erreur Whisper :", e)
        return True

    print("Temps Whisper : {:.2f} s".format(time.time() - t0))

    if not question:
        print("Whisper n'a pas trouvé de parole : ignoré.")
        return True

    print("Vous :", question)

    if question.lower().strip().rstrip(".!?") in MOTS_ARRET:
        changer_mode("parole")
        comportements.parler("Au revoir !")
        return False

    print("Envoi à Ollama...")
    t0 = time.time()

    try:
        answer = demander_ollama(question)
    except Exception as e:
        print("Erreur Ollama :", e)
        return True

    if not answer:
        print("Réponse Ollama vide.")
        return True

    print("Temps Ollama : {:.2f} s".format(time.time() - t0))
    print("Pepper :", answer)

    messages.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer}
    ])
    if len(messages) > 21:
        messages = [messages[0]] + messages[-20:]

    try:
        changer_mode("parole")
        # Voix choisie + geste adapté au contenu de la réponse.
        comportements.parler(answer)
    except Exception as e:
        print("Erreur TTS Pepper :", e)

    return True


# ==========================================
# 7. PROGRAMME PRINCIPAL
# ==========================================

print("\nServices Windows ({}) :".format(WINDOWS_IP))
verifier_service("Whisper", "http://{}:5000/".format(WINDOWS_IP))
verifier_service("Ollama", "http://{}:11434/api/tags".format(WINDOWS_IP))

configurer_pepper()

# Suivi de l'interlocuteur, localisation sonore, gestes, voix.
comportements = Comportements(session, ROBOT_IP)
comportements.demarrer()

try:
    demarrer_micro()
except Exception as e:
    print("\nImpossible de recevoir le son de Pepper :", e)
    print(
        "Pepper n'arrive pas à se connecter à ce script.\n"
        "Sous WSL, activez le mode réseau « mirrored » :\n"
        "  1. Dans C:\\Users\\<vous>\\.wslconfig ajoutez :\n"
        "       [wsl2]\n"
        "       networkingMode=mirrored\n"
        "  2. Dans PowerShell : wsl --shutdown, puis rouvrez WSL.\n"
        "  3. Dans PowerShell ADMINISTRATEUR, autorisez le port {} :\n"
        "       New-NetFirewallHyperVRule -Name PepperAudio "
        "-DisplayName 'Pepper audio' -Direction Inbound "
        "-VMCreatorId '{{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}}' "
        "-Protocol TCP -LocalPorts {}".format(PORT_ECOUTE, PORT_ECOUTE)
    )
    raise SystemExit(1)

detecteur = DetecteurParole()
ecoute = EcouteContinue(detecteur, FREQUENCE)

try:

    # --- Calibration du bruit ambiant ---
    print(
        "\nCalibration du bruit ambiant : "
        "silence pendant {} secondes...".format(CALIBRATION_SECONDS)
    )

    micro.ouvrir()
    morceaux = []
    fin = time.time() + CALIBRATION_SECONDS

    while time.time() < fin:
        morceau = micro.lire(timeout=1.0)
        if morceau is not None:
            morceaux.append(morceau)

    if not morceaux:
        print(
            "Aucun son reçu de Pepper. Vérifiez la connexion réseau "
            "(mode « mirrored » de WSL, pare-feu)."
        )
        raise SystemExit(1)

    niveau = detecteur.calibrer_signal(np.concatenate(morceaux), FREQUENCE)
    print("Bruit ambiant mesuré : {} dB".format(niveau))

    # --- Boucle d'écoute ---
    changer_mode("attente")
    print("\nPepper est prêt ! Parlez-lui quand vous voulez.")
    print("En attente d'une voix...")

    prochaine_verif_personne = time.time() + 1.0

    while True:

        # --- Une nouvelle personne arrive : Pepper la salue ---
        if not ecoute.en_parole and time.time() >= prochaine_verif_personne:
            prochaine_verif_personne = time.time() + 1.0

            if comportements.nouvelle_personne_a_saluer():
                print("\nNouvelle personne détectée : salutation.")
                micro.couper()
                changer_mode("parole")
                comportements.parler(PHRASE_SALUT)
                time.sleep(PAUSE_APRES_PAROLE)
                ecoute.reinitialiser()
                micro.ouvrir()
                changer_mode("attente")
                print("En attente d'une voix...")

        morceau = micro.lire(timeout=2.0)
        if morceau is None:
            print("(aucun son reçu de Pepper depuis 2 s)")
            continue

        deja_en_parole = ecoute.en_parole
        prises = ecoute.ajouter(morceau)

        if ecoute.en_parole and not deja_en_parole:
            changer_mode("ecoute")
            print("\nVoix détectée, j'écoute...")

            # Tourner la tête vers la voix (si personne n'est suivi).
            angle = comportements.regarder_source_sonore()
            if angle is not None:
                print("Source sonore localisée : {}° {}".format(
                    abs(angle), "à gauche" if angle > 0 else "à droite"))

        for signal in prises:

            analyse = detecteur.analyser_signal(signal, FREQUENCE)

            print(
                "Fin de parole ({:.1f} s) : {} | SNR {} dB | "
                "modulation {} dB | bruit {} dB".format(
                    len(signal) / FREQUENCE,
                    analyse["raison"],
                    analyse.get("snr_db"),
                    analyse.get("modulation_db"),
                    analyse.get("bruit_db")
                )
            )

            if not analyse["parole"]:
                changer_mode("attente")
                print("Ignoré. En attente d'une voix...")
                continue

            # Micro coupé pendant que Pepper réfléchit et parle.
            micro.couper()
            changer_mode("reflexion")

            continuer = traiter(signal)

            if not continuer:
                raise KeyboardInterrupt

            time.sleep(PAUSE_APRES_PAROLE)
            ecoute.reinitialiser()
            micro.ouvrir()
            changer_mode("attente")

            print("\nEn attente d'une voix...")

            # Les autres prises éventuelles sont périmées.
            break

except KeyboardInterrupt:
    print("\nArrêt demandé.")

finally:
    arreter_micro()
    try:
        tts.stopAll()
    except Exception:
        pass
    comportements.arreter()
    remettre_leds()
    print("Programme terminé.")
