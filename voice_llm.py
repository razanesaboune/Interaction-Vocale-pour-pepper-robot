
import os
import ctypes
import sys
import time
import subprocess
import winsound

# CUDA configuration for Windows

CUDA_BIN = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\bin"
CUDNN_BIN = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\Library\bin"

# Make CUDA DLLs available to Python and CTranslate2
os.environ["PATH"] = (
    CUDA_BIN + os.pathsep +
    CUDNN_BIN + os.pathsep +
    os.environ.get("PATH", "")
)

# Keep DLL directory handles alive
cuda_handles = [
    os.add_dll_directory(CUDA_BIN),
    os.add_dll_directory(CUDNN_BIN),
]

# Load cuBLAS explicitly
ctypes.WinDLL(os.path.join(CUDA_BIN, "cublas64_12.dll"))

print("CUDA cuBLAS chargé !")

# Imports

import sounddevice as sd
from scipy.io.wavfile import write
from faster_whisper import WhisperModel
import requests

# 1. Configuration

FS = 16000
RECORD_SECONDS = 10
AUDIO_FILE = "audio.wav"
RESPONSE_FILE = "response.wav"

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"

# 2. Load Whisper on GPU

print("Chargement de Whisper medium sur GPU...")

whisper = WhisperModel(
    "medium",
    device="cuda",
    compute_type="float16"
)

print("Whisper medium chargé !")

# 3. Record microphone audio

print("Parle maintenant...")

audio = sd.rec(
    int(RECORD_SECONDS * FS),
    samplerate=FS,
    channels=1,
    dtype="int16"
)

sd.wait()
write(AUDIO_FILE, FS, audio)

print("Enregistrement terminé")

# 4. Speech-to-text

print("Transcription en cours...")

start = time.time()

segments, info = whisper.transcribe(
    AUDIO_FILE,
    language="fr",
    beam_size=5,
    vad_filter=True,
    condition_on_previous_text=False
)

# Important: consuming segments runs the transcription
question = " ".join(
    segment.text.strip()
    for segment in segments
).strip()

elapsed = time.time() - start

print("Vous :", question)
print("Temps transcription :", round(elapsed, 2), "secondes")

# Do not send empty transcriptions to Ollama
if not question:
    print("Aucune parole détectée. Fin du programme.")
    sys.exit(0)

# 5. Send question to Ollama

print("Envoi à Ollama...")

messages = [
    {
        "role": "system",
        "content": (
            "Tu es Pepper, un robot assistant. "
            "Réponds toujours dans la même langue que l'utilisateur. "
            "Si l'utilisateur parle français, réponds uniquement en français. "
            "Si l'utilisateur parle anglais, réponds uniquement en anglais. "
            "Réponds de manière courte, naturelle et claire."
        )
    },
    {
        "role": "user",
        "content": question
    }
]

data = {
    "model": OLLAMA_MODEL,
    "messages": messages,
    "stream": False
}

try:
    response = requests.post(
        OLLAMA_URL,
        json=data,
        timeout=120
    )
    response.raise_for_status()

    answer = response.json()["message"]["content"].strip()

except requests.RequestException as e:
    print("Erreur de connexion à Ollama :", e)
    sys.exit(1)

print("Pepper :", answer)

if not answer:
    print("Ollama n'a pas généré de réponse.")
    sys.exit(0)

# 6. Text-to-speech with Piper

print("Génération de la voix...")

try:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "piper",
            "-m",
            "fr_FR-siwis-medium",
            "-f",
            RESPONSE_FILE,
            "--",
            answer
        ],
        check=True
    )

except subprocess.CalledProcessError as e:
    print("Erreur Piper :", e)
    sys.exit(1)

# 7. Play the response

print("Pepper parle...")

winsound.PlaySound(
    RESPONSE_FILE,
    winsound.SND_FILENAME
)

print("Terminé !")
