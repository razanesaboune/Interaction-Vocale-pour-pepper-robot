import torch
from TTS.api import TTS

device = "cuda" if torch.cuda.is_available() else "cpu"

print("Device:", device)

tts = TTS(
    "tts_models/multilingual/multi-dataset/xtts_v2"
).to(device)

tts.tts_to_file(
    text="Bonjour, je suis Pepper. La capitale du Liban est Beyrouth.",
    speaker="Ana Florence",
    language="fr",
    file_path="xtts_output.wav"
)

print("Audio généré : xtts_output.wav")