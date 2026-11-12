
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

# 5. TRANSCRIPTION AUDIO

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
            vad_filter=True,
            condition_on_previous_text=False
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

        print("Transcription :", text)

        return jsonify({
            "text": text
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
