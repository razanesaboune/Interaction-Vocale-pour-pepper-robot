import qi

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect(f"tcp://{ip}:{port}")

tts = session.service("ALTextToSpeech")
tts.say("Bonjour, test de connexion")