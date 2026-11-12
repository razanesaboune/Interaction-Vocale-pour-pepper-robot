
import qi
import time
import requests
import paramiko


# 1. CONFIGURATION

ROBOT_IP = "169.254.107.138"
ROBOT_PORT = 9559

# Services lancés sur Windows
WINDOWS_IP = "172.23.96.1"

WHISPER_URL = (
    "http://{}:5000/transcribe".format(WINDOWS_IP)
)

OLLAMA_URL = (
    "http://{}:11434/api/chat".format(WINDOWS_IP)
)

OLLAMA_MODEL = "llama3.2:3b"

REMOTE_AUDIO = (
    "/home/nao/recordings/microphones/question.wav"
)

LOCAL_AUDIO = "question.wav"

RECORD_SECONDS = 5

HEAD_SENSOR = (
    "Device/SubDeviceList/Head/Touch/Front/Sensor/Value"
)

# 2. CONNEXION À PEPPER

print("Connexion à Pepper...")

session = qi.Session()

try:
    session.connect(
        "tcp://{}:{}".format(ROBOT_IP, ROBOT_PORT)
    )
    print("Connecté à Pepper !")

except Exception as e:
    print("Erreur connexion Pepper :", e)
    raise SystemExit(1)

tts = session.service("ALTextToSpeech")
recorder = session.service("ALAudioRecorder")
memory = session.service("ALMemory")

tts.setVolume(0.6)

# 3. CONTRÔLE DES COMPORTEMENTS DE PEPPER


def configurer_pepper():

    print("\nConfiguration de Pepper...")

    # 1. Arrêter les comportements autonomes
    try:
        life = session.service("ALAutonomousLife")

        if life.getState() != "disabled":
            life.setState("disabled")

        print("Vie autonome désactivée.")

    except Exception as e:
        print("Erreur vie autonome :", e)

    # 2. Désactiver le suivi des personnes
    try:
        awareness = session.service("ALBasicAwareness")
        awareness.stopAwareness()

        print("Suivi automatique désactivé.")

    except Exception as e:
        print("Erreur awareness :", e)

    # 3. Désactiver les gestes pendant la parole
    try:
        animated_speech = session.service("ALAnimatedSpeech")
        animated_speech.setBodyLanguageMode(0)

        print("Gestes de parole désactivés.")

    except Exception as e:
        print("Erreur gestes :", e)

    # 4. Désactiver les mouvements de respiration
    try:
        motion = session.service("ALMotion")

        motion.setBreathEnabled("Body", False)

        print("Mouvements de respiration désactivés.")

    except Exception as e:
        print("Erreur respiration :", e)

    # 5. Maintenir une posture debout
    try:
        posture = session.service("ALRobotPosture")

        if posture.getPosture() != "Stand":
            posture.goToPosture("Stand", 0.3)

        print("Posture debout demandée.")

    except Exception as e:
        print("Erreur posture :", e)

    # 6. Arrêter les paroles en cours
    try:
        tts.stopAll()
        print("Paroles arrêtées.")

    except Exception as e:
        print("Erreur TTS :", e)

    print("Pepper configuré : debout et silencieux.")


# ==========================================
# 4. HISTORIQUE OLLAMA
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

# ==========================================
# 5. ATTENDRE LE TOUCHER DE TÊTE
# ==========================================

def attendre_touch():

    print(
        "\nTouchez l'avant de la tête "
        "de Pepper pour parler..."
    )

    # Attendre un toucher
    while memory.getData(HEAD_SENSOR) < 0.5:
        time.sleep(0.1)

    print("Tête touchée !")

    # Arrêter toute parole TTS en cours
    try:
        tts.stopAll()
    except Exception as e:
        print("Erreur arrêt TTS :", e)

    # Attendre le retrait de la main
    while memory.getData(HEAD_SENSOR) >= 0.5:
        time.sleep(0.1)

    time.sleep(0.3)

    print("Pepper est silencieux et prêt à écouter.")


# ==========================================
# 6. RÉCUPÉRER L'AUDIO DE PEPPER
# ==========================================

def recuperer_audio():

    ssh = paramiko.SSHClient()

    # Prototype sur réseau de confiance.
    # En production, vérifier la clé SSH.
    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    try:
        ssh.connect(
            ROBOT_IP,
            username="nao",
            timeout=15
        )

        sftp = ssh.open_sftp()

        try:
            sftp.get(
                REMOTE_AUDIO,
                LOCAL_AUDIO
            )
        finally:
            sftp.close()

    finally:
        ssh.close()


# ==========================================
# 7. VÉRIFICATION DES SERVICES WINDOWS
# ==========================================

def verifier_service(nom, url):

    try:
        response = requests.get(
            url,
            timeout=5
        )

        response.raise_for_status()

        print("{} accessible !".format(nom))
        return True

    except Exception as e:
        print("{} inaccessible : {}".format(nom, e))
        return False


print("\nVérification des services Windows...")

whisper_ok = verifier_service(
    "Whisper",
    "http://{}:5000/".format(WINDOWS_IP)
)

ollama_ok = verifier_service(
    "Ollama",
    "http://{}:11434/api/tags".format(WINDOWS_IP)
)

if not whisper_ok:
    print(
        "Attention : vérifier le serveur Whisper. "
        "La route / peut répondre 404 sur une ancienne version."
    )

if not ollama_ok:
    print(
        "Attention : Ollama n'est pas accessible depuis WSL."
    )

# ==========================================
# 8. BOUCLE PRINCIPALE
# ==========================================

print("\nPepper est prêt !")

try:

    while True:

        # ----------------------------------
        # ÉTAPE 1 : TOUCHER LA TÊTE
        # ----------------------------------

        attendre_touch()

        print(
            "\nParlez maintenant pendant {} secondes..."
            .format(RECORD_SECONDS)
        )

        # ----------------------------------
        # ÉTAPE 2 : ENREGISTREMENT
        # ----------------------------------

        try:

            # Sécurité : arrêter le TTS
            # avant de démarrer l'écoute.
            try:
                tts.stopAll()
            except Exception:
                pass

            try:
                recorder.stopMicrophonesRecording()
            except Exception:
                pass

            channels = [0, 0, 1, 0]

            recorder.startMicrophonesRecording(
                REMOTE_AUDIO,
                "wav",
                16000,
                channels
            )

            time.sleep(RECORD_SECONDS)

            recorder.stopMicrophonesRecording()

            print("Enregistrement terminé !")

        except Exception as e:

            print("Erreur enregistrement :", e)

            try:
                recorder.stopMicrophonesRecording()
            except Exception:
                pass

            continue

        # ----------------------------------
        # ÉTAPE 3 : TRANSFERT SFTP
        # ----------------------------------

        print("Récupération audio depuis Pepper...")

        try:

            recuperer_audio()

            print("Audio récupéré !")

        except Exception as e:

            print("Erreur transfert audio :", e)
            continue

        # ----------------------------------
        # ÉTAPE 4 : WHISPER GPU
        # ----------------------------------

        print("Transcription avec Whisper GPU...")

        start_whisper = time.time()

        try:

            with open(LOCAL_AUDIO, "rb") as audio_file:

                response = requests.post(
                    WHISPER_URL,
                    files={
                        "audio": (
                            "question.wav",
                            audio_file,
                            "audio/wav"
                        )
                    },
                    timeout=120
                )

            response.raise_for_status()

            question = (
                response.json()
                .get("text", "")
                .strip()
            )

        except Exception as e:

            print("Erreur transcription Whisper :", e)
            continue

        whisper_time = time.time() - start_whisper

        print(
            "Temps Whisper : {:.2f} secondes"
            .format(whisper_time)
        )

        if not question:

            print("Aucune parole détectée.")
            continue

        print("Vous :", question)

        # ----------------------------------
        # ÉTAPE 5 : COMMANDE D'ARRÊT
        # ----------------------------------

        question_lower = (
            question.lower().strip().rstrip(".!?")
        )

        if question_lower in [
            "stop",
            "arrête",
            "arrête-toi",
            "quitte",
            "au revoir"
        ]:

            tts.say("Au revoir !")
            break

        # ----------------------------------
        # ÉTAPE 6 : OLLAMA
        # ----------------------------------

        print("Envoi à Ollama...")

        start_ollama = time.time()

        conversation = messages + [
            {
                "role": "user",
                "content": question
            }
        ]

        try:

            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": conversation,
                    "stream": False
                },
                timeout=120
            )

            response.raise_for_status()

            answer = (
                response.json()["message"]["content"]
                .strip()
            )

        except Exception as e:

            print("Erreur Ollama :", e)
            continue

        if not answer:

            print("Réponse Ollama vide.")
            continue

        ollama_time = time.time() - start_ollama

        print(
            "Temps Ollama : {:.2f} secondes"
            .format(ollama_time)
        )

        print("Pepper :", answer)

        # ----------------------------------
        # ÉTAPE 7 : HISTORIQUE
        # ----------------------------------

        messages.extend([
            {
                "role": "user",
                "content": question
            },
            {
                "role": "assistant",
                "content": answer
            }
        ])

        if len(messages) > 21:
            messages = [messages[0]] + messages[-20:]

        # ----------------------------------
        # ÉTAPE 8 : PEPPER PARLE
        # ----------------------------------

        try:

            print("Pepper va parler...")

            start_tts = time.time()

            # Seule la réponse d'Ollama
            # est prononcée ici.
            tts.say(answer)

            tts_time = time.time() - start_tts

            print(
                "Temps parole Pepper : {:.2f} secondes"
                .format(tts_time)
            )

            print("Pepper a terminé !")

        except Exception as e:

            print("Erreur TTS Pepper :", e)

        # ----------------------------------
        # ÉTAPE 9 : PAUSE ANTI-ÉCHO
        # ----------------------------------

        time.sleep(2)

except KeyboardInterrupt:

    print("\nArrêt demandé au clavier.")

finally:

    try:
        recorder.stopMicrophonesRecording()
    except Exception:
        pass

    try:
        tts.stopAll()
    except Exception:
        pass

    print("Programme terminé.")
