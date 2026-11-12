import qi
import time

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

memory = session.service("ALMemory")
tts = session.service("ALTextToSpeech")

head_sensor = "FrontTactilTouched"

compteur = 0
etat_precedent = 0

print("Touchez la tête 3 fois...")

while True:
    valeur = memory.getData(head_sensor)

    # Détecter seulement le début d'un nouveau toucher
    if valeur > 0 and etat_precedent == 0:
        compteur += 1
        print("Nombre de touches :", compteur)

        if compteur == 3:
            tts.say("Bonjour")
            print("Pepper dit : Bonjour")

            # Optionnel : remettre le compteur à zéro
            compteur = 0

    etat_precedent = valeur

    time.sleep(0.1)