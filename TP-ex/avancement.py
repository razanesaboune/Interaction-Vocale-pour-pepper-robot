import qi
import time

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

motion = session.service("ALMotion")
memory = session.service("ALMemory")

# Capteur avant de la tête
head_sensor = "FrontTactilTouched"

etat_precedent = 0
en_mouvement = True

# Réveiller Pepper
motion.wakeUp()

print("Pepper avance")
print("Touchez la tête pour arrêter / reprendre")

# Commence à avancer
motion.moveToward(0.2, 0.0, 0.0)

while True:
    valeur = memory.getData(head_sensor)

    # Nouveau toucher détecté
    if valeur > 0 and etat_precedent == 0:

        if en_mouvement:
            # Arrêt
            motion.stopMove()
            en_mouvement = False
            print("Pepper arrêté")

        else:
            # Reprendre
            motion.moveToward(0.2, 0.0, 0.0)
            en_mouvement = True
            print("Pepper avance")

    etat_precedent = valeur
    time.sleep(0.1)