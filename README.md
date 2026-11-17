# Pepper – Dialogue vocal autonome

Projet transverse : amélioration du système de dialogue du robot Pepper
(NAOqi 2.5.10). Pepper écoute en continu, détecte quand on lui parle
(en ignorant le bruit ambiant), transcrit avec **Whisper**, répond avec
**Ollama** (`llama3.2:3b`) et parle avec des **gestes adaptés**, en
suivant son interlocuteur du regard.

```
 Micro Pepper ──(flux audio direct, port 9600)──► WSL : pepper_autonome.py
                                                    │  detection_parole.py (VAD)
                                                    ├─► Whisper (Windows, :5000)
                                                    ├─► Ollama  (Windows, :11434)
 Pepper ◄── parole + gestes + LEDs ─────────────────┘  comportements.py
```

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `pepper_autonome.py` | **Script principal.** Écoute continue, conversation, LEDs |
| `detection_parole.py` | Détection de parole robuste au bruit (seuil adaptatif, VAD) |
| `comportements.py` | Gestes, suivi de l'interlocuteur, localisation sonore, voix |
| `whisper_server.py` | Serveur de transcription (Windows, GPU) |
| `pepper_test_vocal.py` | Ancienne version : on touche la tête pour parler (secours) |
| `fr_FR-siwis-medium.onnx` | Voix Piper française (optionnelle) |
| `pepper_linux/` | Environnement Python **WSL** (qi, numpy, requests, paramiko) |
| `pepper/` | Ancien environnement Python Windows (sans `qi`) |

---

## Prérequis (une seule fois)

1. **WSL en réseau « mirrored »**, pour que Pepper puisse envoyer son son à WSL.
   Le fichier `C:\Users\2002r\.wslconfig` contient :
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
   ✅ Déjà fait. Après un `wsl --shutdown`, les interfaces mettent environ 30 s à revenir.

2. **Pare-feu Hyper-V : autoriser le port 9600.** Dans PowerShell **administrateur** :
   ```powershell
   New-NetFirewallHyperVRule -Name PepperAudio -DisplayName 'Pepper audio (WSL)' -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 9600
   ```
   ⚠️ **À faire.** Sans cette règle, le script affiche « Can't find service ».

3. **Ollama accessible depuis WSL.** La variable `OLLAMA_HOST=0.0.0.0` est déjà enregistrée (`setx`).

4. *(Optionnel)* **Voix Piper**, plus claire :
   ```bash
   pepper_linux/bin/pip install piper-tts
   ```
   Puis mettez `VOIX = "piper"` dans `comportements.py`.

---

## Lancement

**1. Brancher Pepper** en Ethernet et l'allumer. Son adresse est `169.254.9.153`. Si elle change, modifiez `ROBOT_IP` dans `pepper_autonome.py`.

**2. Démarrer Ollama** (Windows, PowerShell), si l'icône Ollama n'est pas déjà active :
```powershell
ollama serve
```

**3. Démarrer le serveur Whisper** (Windows, PowerShell) :
```powershell
cd "C:\Users\2002r\Desktop\Projet Transverse"
C:\Users\2002r\miniconda3\envs\whisper_cuda\python.exe whisper_server.py
```
Attendre le message « Whisper prêt ! ».

**4. Lancer Pepper** (terminal WSL) :
```bash
cd "/mnt/c/Users/2002r/Desktop/Projet Transverse"
source pepper_linux/bin/activate
python pepper_autonome.py
```

**5. Utilisation**
- Pendant les 3 s de calibration, **ne parlez pas** : Pepper mesure le bruit ambiant.
- Ensuite, parlez-lui normalement, sans le toucher.
- Pour arrêter : dites « stop » ou « au revoir », ou faites Ctrl+C.

### Couleurs des yeux

| Yeux | Oreilles | Mode |
|---|---|---|
| ⚪ Blanc | faibles | En attente |
| 🟢 Vert | allumées | Il vous écoute |
| 🟠 Orange | moyennes | Il réfléchit (Whisper + Ollama) |
| 🔵 Bleu | éteintes | Il parle |

---

## Réglages utiles

| Paramètre | Fichier | Effet |
|---|---|---|
| `SEUIL_SNR_DB = 3.0` | `detection_parole.py` | ↑ si du bruit déclenche Pepper, ↓ s'il ne vous entend pas |
| `FIN_SILENCE_MS = 900` | `detection_parole.py` | Silence (ms) avant que Pepper considère que vous avez fini |
| `MODULATION_MIN_DB = 2.3` | `detection_parole.py` | ↓ si une voix monotone est rejetée |
| `VOIX` | `comportements.py` | `"pepper_claire"`, `"pepper_origine"` ou `"piper"` |
| `MODE_SUIVI` | `comportements.py` | `"Head"` (tête seule) ou `"BodyRotation"` (tourne sur lui-même) |
| `REGLES_GESTES` | `comportements.py` | Mots-clés → animations |
| `MODES_LEDS` | `pepper_autonome.py` | Couleurs des yeux (hexadécimal) |

Tester le détecteur sur un fichier, sans robot :
```bash
python detection_parole.py question.wav
python detection_parole.py --bruit silence.wav question.wav
```

---

## Comment ça marche (résumé)

**Détection de parole** (`detection_parole.py`). Le ventilateur interne de Pepper fait un bruit constant vers 415 Hz, presque aussi fort qu'une voix. La détection suit ces étapes :
1. Spectre (FFT) par trames de 20 ms dans la bande 300–3400 Hz.
2. Profil du bruit appris par fréquence : calibration au démarrage, puis mise à jour continue.
3. Rapport signal/bruit moyenné sur toutes les fréquences et lissé sur 100 ms. Il y a voix au-dessus de 3 dB.
4. Rejet des sons trop courts (claquements), trop faibles (voix lointaines) ou trop stables (non modulés, comme un ventilateur).
5. Début de prise de parole après 200 ms de voix, fin après 900 ms de silence.

**Comportements** (`comportements.py`) :
- `ALBasicAwareness` suit les visages et salue une nouvelle personne.
- `ALSoundLocalization` fait tourner la tête vers la voix détectée.
- `ALAnimatedSpeech` lance un geste choisi selon les mots de la réponse.

**Serveur Whisper** : VAD Silero, rejet des segments peu fiables et des hallucinations (« Sous-titres réalisés par… »).

---

## Dépannage

| Problème | Solution |
|---|---|
| `Can't find service: MicroPepperAutonome` | Pare-feu (prérequis 2), ou WSL pas en mode mirrored |
| `Aucun son reçu de Pepper` | Idem, ou le robot ne répond pas : `ping 169.254.9.153` |
| Whisper / Ollama « inaccessible » | Lancer les services (étapes 2-3). Depuis WSL : `curl http://127.0.0.1:11434/` |
| Pepper se déclenche tout seul | Augmenter `SEUIL_SNR_DB` (3.5 ou 4) |
| Pepper ne vous entend pas | Rapprochez-vous, baissez `SEUIL_SNR_DB` (2.5) |
| Pepper coupe vos phrases | Augmenter `FIN_SILENCE_MS` (1200) |
| L'adresse du robot a changé | Modifier `ROBOT_IP` dans `pepper_autonome.py` |

---

## État du projet

- ✅ Détection de parole testée hors ligne sur les enregistrements du robot (45 cas sur fichiers, 4 prises de parole sur un flux simulé d'une minute).
- ✅ Testés sur le robot : LEDs, animations, format de la localisation sonore, réglages de voix.
- ⚠️ Conversation autonome complète **pas encore testée sur le robot** : la règle de pare-feu (port 9600) est à ajouter.
- ⬜ Piper pas encore installé.
