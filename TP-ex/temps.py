import qi
import time
import math

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

motion = session.service("ALMotion")

motion.wakeUp()

angle = 2 * math.pi / 3

# Triangle
for i in range(3):
    print("Côté", i + 1)

    motion.moveToward(0.15, 0.0, 0.0)
    time.sleep(2)
    motion.stopMove()

    motion.moveTo(0.0, 0.0, angle)

print("Triangle terminé")

# Attendre 3 secondes
time.sleep(3)

# Simuler une posture de fin adaptée à Pepper
motion.setAngles(
    ["HeadPitch", "LShoulderPitch", "RShoulderPitch"],
    [0.4, 1.3, 1.3],
    0.2
)

print("Posture finale")