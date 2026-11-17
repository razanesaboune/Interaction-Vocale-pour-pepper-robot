
import os
import ctypes

from flask import Flask, request, jsonify

# 1. CONFIGURATION CUDA WINDOWS

CUDA_BIN = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\bin"
CUDNN_BIN = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\Library\bin"

os.environ["PATH"] = (
    CUDA_BIN
    + os.pathsep
    + CUDNN_BIN
    + os.pathsep
    + os.environ.get("PATH", "")
)

# Conserver les handles pendant toute l'exécution
cuda_handles = [
    os.add_dll_directory(CUDA_BIN),
    os.add_dll_directory(CUDNN_BIN)
]

ctypes.WinDLL(
    os.path.join(CUDA_BIN, "cublas64_12.dll")
)

print("CUDA cuBLAS chargé !")

# IMPORTANT : importer Whisper après CUDA
from faster_whisper import WhisperModel

# 2. SERVEUR FLASK

app = Flask(__name__)

# 3. CHARGEMENT WHISPER SUR GPU
print("Chargement Whisper medium sur GPU...")

whisper = WhisperModel(
    "medium",
    device="cuda",
    compute_type="float16"
)

print("Whisper prêt !")

# 4. ROUTE DE VÉRIFICATION

@app.route("/", methods=["GET"])
def accueil():
    return jsonify({
        "status": "ok",
        "message": "Serveur Whisper GPU prêt"
    })

# 5. FILTRAGE DU BRUIT ET DES HALLUCINATIONS

# VAD Silero : plus strict que les valeurs par défaut.
VAD_PARAMETRES = {
    "threshold": 0.5,               # probabilité de parole minimale
    "min_speech_duration_ms": 250,  # ignore les bruits très brefs
    "min_silence_duration_ms": 500,
    "speech_pad_ms": 200,
}

# Seuils de confiance de Whisper (mêmes valeurs que Whisper d'OpenAI).
NO_SPEECH_MAX = 0.6
LOGPROB_MIN = -1.0
COMPRESSION_MAX = 2.4

# Phrases que Whisper « invente » souvent sur du silence ou du bruit
# (issues des sous-titres de ses données d'entraînement).
HALLUCINATIONS = [
    "sous-titres réalisés par",
    "sous-titrage",
    "amara.org",
    "merci d'avoir regardé",
    "abonnez-vous",
    "n'oubliez pas de vous abonner",
    "radio-canada",
]


def segment_suspect(segment):
    """Retourne la raison du rejet, ou None si le segment est fiable."""

    texte = segment.text.strip().lower()

    if not texte:
        return "vide"

    if any(h in texte for h in HALLUCINATIONS):
        return "hallucination connue"

    if (segment.no_speech_prob > NO_SPEECH_MAX
            and segment.avg_logprob < LOGPROB_MIN):
        return "probablement pas de parole (no_speech={:.2f})".format(
            segment.no_speech_prob)

    if segment.compression_ratio > COMPRESSION_MAX:
        return "texte répétitif (compression={:.2f})".format(
            segment.compression_ratio)

    return None


# 6. TRANSCRIPTION AUDIO

@app.route("/transcribe", methods=["POST"])
def transcribe():

    audio = request.files.get("audio")

    if audio is None:
        return jsonify({
            "error": "Audio manquant"
        }), 400

    try:
        segments, info = whisper.transcribe(
            audio,
            language="fr",
            beam_size=5,
            # VAD Silero intégré : ne transcrit que les zones de parole.
            vad_filter=True,
            vad_parameters=VAD_PARAMETRES,
            condition_on_previous_text=False
        )

        gardes = []
        rejetes = []

        for segment in segments:
            raison = segment_suspect(segment)
            if raison:
                rejetes.append((segment.text.strip(), raison))
            else:
                gardes.append(segment.text.strip())

        text = " ".join(gardes).strip()

        for texte_rejete, raison in rejetes:
            print("Segment rejeté ({}) : {}".format(raison, texte_rejete))

        print("Transcription :", text)

        return jsonify({
            "text": text,
            "segments_rejetes": len(rejetes)
        })

    except Exception as e:
        print("Erreur Whisper :", e)

        return jsonify({
            "error": "Erreur de transcription"
        }), 500

# ==========================================
# 6. DÉMARRAGE DU SERVEUR
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
