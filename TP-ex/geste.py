import qi

ip = "169.254.199.30"
port = 9559

session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))

tts = session.service("ALTextToSpeech")
motion = session.service("ALMotion")
posture = session.service("ALRobotPosture")

# 1. Réveiller le robot et le mettre debout
motion.wakeUp()
posture.goToPosture("StandInit", 0.5)

# 2. Lever le bras droit
joints = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll"]
angles = [-1.0, -0.3, 0.5, 1.0]
motion.angleInterpolation(joints, angles, 1.5, True)

# 3. Parler pendant que le bras salue (_async=True : le robot parle sans bloquer)
tts.say("Bonjour tout le monde. Je suis un robot NAO.", _async=True)

# 4. Agiter l'avant-bras : le coude va et vient
for i in range(3):
    motion.angleInterpolation("RElbowRoll", 1.5, 0.4, True)
    motion.angleInterpolation("RElbowRoll", 0.5, 0.4, True)

# 5. Revenir en position debout normale
posture.goToPosture("StandInit", 0.5)

