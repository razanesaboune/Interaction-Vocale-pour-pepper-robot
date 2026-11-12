import qi
import math
import time

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

motion = session.service("ALMotion")

motion.wakeUp()

distance = 0.3
angle = math.pi / 2

for i in range(4):
    print("Côté", i + 1)

    # avancer
    motion.moveToward(0.15, 0.0, 0.0)
    time.sleep(2)
    motion.stopMove()

    # tourner 90°
    motion.moveTo(0.0, 0.0, angle)

print("Carré terminé")