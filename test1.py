import requests

url = "http://127.0.0.1:11434/api/generate"

data = {
    "model": "llama3.2:3b",
    "prompt": "Bonjour, présente-toi comme Pepper en une phrase.",
    "stream": False
}

response = requests.post(
    url,
    json=data,
    timeout=120
)

print("Status:", response.status_code)
print("Réponse:", response.json()["response"])