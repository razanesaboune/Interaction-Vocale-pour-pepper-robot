import qi
import time

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

memory = session.service("ALMemory")
tts = session.service("ALTextToSpeech")

capteurs = {
    # Tête
    "Device/SubDeviceList/Head/Touch/Front/Sensor/Value": "avant de la tête",
    "Device/SubDeviceList/Head/Touch/Middle/Sensor/Value": "milieu de la tête",
    "Device/SubDeviceList/Head/Touch/Rear/Sensor/Value": "arrière de la tête",

    # Main gauche
    "Device/SubDeviceList/LHand/Touch/Left/Sensor/Value": "côté gauche de la main gauche",
    "Device/SubDeviceList/LHand/Touch/Back/Sensor/Value": "dos de la main gauche",
    "Device/SubDeviceList/LHand/Touch/Right/Sensor/Value": "côté droit de la main gauche",

    # Main droite
    "Device/SubDeviceList/RHand/Touch/Left/Sensor/Value": "côté gauche de la main droite",
    "Device/SubDeviceList/RHand/Touch/Back/Sensor/Value": "dos de la main droite",
    "Device/SubDeviceList/RHand/Touch/Right/Sensor/Value": "côté droit de la main droite",
}

etat_precedent = {nom: 0 for nom in capteurs}

print("Touchez un capteur...")

while True:
    for nom_capteur, phrase in capteurs.items():
        try:
            valeur = memory.getData(nom_capteur)

            if valeur > 0.5 and etat_precedent[nom_capteur] <= 0.5:
                print("Touché :", phrase)
                tts.say(phrase)

            etat_precedent[nom_capteur] = valeur

        except Exception as e:
            print("Indisponible :", nom_capteur)

    time.sleep(0.1)