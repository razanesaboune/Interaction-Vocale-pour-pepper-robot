import requests

url = "http://127.0.0.1:11434/api/chat"

messages = [
    {
        "role": "system",
        "content": (
            "Tu es Pepper, le robot assistant. "
            "L'utilisateur est une personne différente de toi. "
            "Ne confonds jamais les informations sur Pepper avec celles de l'utilisateur. "
            "Quand l'utilisateur donne son nom, mémorise-le comme le nom de l'utilisateur. "
            "Réponds brièvement, naturellement et en français."
        )
    }
]

while True:
    question = input("Vous : ")

    if question.lower() in ["exit", "quit"]:
        break

    messages.append({
        "role": "user",
        "content": question
    })

    data = {
        "model": "llama3.2:3b",
        "messages": messages,
        "stream": False
    }

    response = requests.post(url, json=data, timeout=120)

    answer = response.json()["message"]["content"]

    print("Pepper :", answer)

    messages.append({
        "role": "assistant",
        "content": answer
    })