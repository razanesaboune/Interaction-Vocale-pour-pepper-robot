import qi
ip = "169.254.199.30"
port = 9559
session = qi.Session()
session.connect("tcp://" + ip + ":" + str(port))
#ex 1 presente en public 
tts = session.service("ALTextToSpeech")
tts.say("Bonjour, je fonctionne avec Python 3 et qi.")

