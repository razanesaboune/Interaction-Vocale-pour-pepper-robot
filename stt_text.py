import sounddevice as sd
from scipy.io.wavfile import write
from faster_whisper import WhisperModel

fs = 16000
seconds = 5

print("1. Parle maintenant...")

audio = sd.rec(
    int(seconds * fs),
    samplerate=fs,
    channels=1,
    dtype="int16"
)

sd.wait()
write("audio.wav", fs, audio)

print("2. Enregistrement terminé")

print("3. Chargement du modèle Whisper...")
model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("4. Modèle chargé")

print("5. Transcription...")
segments, info = model.transcribe(
    "audio.wav",
    language="fr",
    initial_prompt="Le robot s'appelle Pepper."
)

text = ""

for segment in segments:
    print("Segment :", segment.text)
    text += segment.text

print("Texte reconnu :", text)