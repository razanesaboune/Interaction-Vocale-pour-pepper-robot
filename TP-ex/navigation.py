import qi

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

motion = session.service("ALMotion")
posture = session.service("ALRobotPosture")

# Mettre Pepper debout
posture.goToPosture("StandInit", 0.5)

# Avancer de 1 mètre
motion.moveTo(1.0, 0.0, 0.0)

print("Pepper a avancé de 1 mètre")