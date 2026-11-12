import qi
import requests

ROBOT_IP = "169.254.134.197"
ROBOT_PORT = 9559

OLLAMA_URL = "http://172.23.96.1:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"


# Connexion à Pepper

session = qi.Session()

print("Connexion à Pepper...")

session.connect(
    f"tcp://{ROBOT_IP}:{ROBOT_PORT}"
)

print("Connecté à Pepper ")

tts = session.service("ALTextToSpeech")


# Mémoire de conversation

messages = [
    {
        "role": "system",
        "content": (
            "Tu es Pepper, un robot assistant. "
            "Réponds toujours dans la même langue que l'utilisateur. "
            "Réponds brièvement, naturellement et clairement."
        )
    }
]


# Dialogue

while True:

    question = input("\nVous : ").strip()

    if question.lower() in ["quit", "exit"]:
        print("Fin du programme.")
        break

    if not question:
        continue

    messages.append({
        "role": "user",
        "content": question
    })

    try:

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        answer = response.json()["message"]["content"].strip()

        print("Pepper :", answer)

        messages.append({
            "role": "assistant",
            "content": answer
        })

        # Pepper prononce la réponse
        tts.say(answer)

    except Exception as e:
        print("Erreur :", e)