# Projet Pepper – notes pour Claude

Lis `README.md` pour l'architecture, les réglages et le dépannage.
L'utilisatrice parle français : réponds en français.

## Environnement
- Windows 11. Le code robot tourne dans **WSL** avec le venv `pepper_linux/` (Python 3.12, `qi` 3.1.5). Le venv Windows `pepper/` n'a pas `qi`.
- Robot Pepper NAOqi 2.5.10 sur `169.254.9.153:9559` (Ethernet direct, le PC est en `169.254.157.220`).
- WSL est en réseau **mirrored** (`C:\Users\2002r\.wslconfig`) : depuis WSL, Whisper et Ollama sont sur `127.0.0.1`. Après `wsl --shutdown`, les interfaces mettent environ 30 s à revenir.
- Whisper : `whisper_server.py` sur Windows, env conda `C:\Users\2002r\miniconda3\envs\whisper_cuda`, port 5000.
- Ollama : Windows, port 11434, `OLLAMA_HOST=0.0.0.0` enregistré, modèle `llama3.2:3b`.

## Commandes (depuis l'outil Bash ; le chemin contient un espace, garder les guillemets)
```bash
# Vérifier les services et le robot
wsl.exe -e bash -lc 'for p in 5000 11434; do (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null && echo $p OUVERT || echo $p ferme; done; ping -c1 -W2 169.254.9.153 >/dev/null && echo ROBOT_OK || echo ROBOT_KO'

# Lancer le script principal (interactif : de préférence dans le terminal de l'utilisatrice)
wsl.exe -e bash -lc 'cd "/mnt/c/Users/2002r/Desktop/Projet Transverse" && pepper_linux/bin/python -u pepper_autonome.py'

# Tester le détecteur hors ligne
wsl.exe -e bash -lc 'cd "/mnt/c/Users/2002r/Desktop/Projet Transverse" && pepper_linux/bin/python -B detection_parole.py question.wav'
```
- Utiliser `python -B` pour les tests, pour ne pas laisser de `__pycache__`.
- Toujours un `timeout` sur les scripts qui se connectent au robot.

## Points d'attention
- Le streaming audio (`ALAudioDevice` → `processRemote`) exige que Pepper se connecte au script : `session.listen("tcp://0.0.0.0:9600")` + une règle de pare-feu Hyper-V sur le port 9600 (commande dans le README, à lancer par l'utilisatrice en PowerShell admin). Symptôme si elle manque : `Can't find service`.
- Les commandes admin (UAC) et `pip install` ont été refusées par le mode auto : demander à l'utilisatrice de les lancer.
- Le bruit dominant est le ventilateur de Pepper (vers 415 Hz, environ -30 dB, presque aussi fort qu'une voix). Ne pas revenir à un simple seuil d'énergie (voir le docstring de `detection_parole.py`).
- Ne pas faire bouger ou parler le robot pour un test sans prévenir l'utilisatrice.
- `pepper_test_vocal.py` = ancienne version (toucher la tête, enregistrement + SFTP), gardée en secours.

## RAG (dossier `RAG/`, voir `RAG/RAPPORT_RAG.md`)
- Tourne sous **Windows** avec `pepper\Scripts\python.exe` (selenium, chromadb, bs4 installés) ; Ollama `embeddinggemma` sur `127.0.0.1:11434`.
- Chaîne : `rag_scraper_selenium.py` (site -> `data/html_cache/`, ~30 min) puis `rag_pipeline.py` (nettoyage -> `data/kb/`, chunking, ChromaDB `esiee_it_kb`, évaluation sur `eval/questions.json`, ~3 min). `--depuis-cache` re-extrait sans re-télécharger.
- `data/documents.json` = version brute d'origine, ne pas l'écraser ; la version nettoyée est `data/kb/`.
- Recherche : `rag_recherche.Recherche().rechercher(q, k, mode="hybride")`. Réglages testés (préfixe « question answering », RRF k=20, fiche formation dans chaque chunk) : hit@5 0,909, MRR 0,778 sur 254 questions.
- Pas encore branché dans `pepper_autonome.py` (`demander_ollama`).

## État (2026-11-17)
- À faire par l'utilisatrice : règle de pare-feu (port 9600), puis premier essai réel de `pepper_autonome.py`.
- Piper (`VOIX = "piper"`) non installé : `pepper_linux/bin/pip install piper-tts`.
- Rien n'est commité depuis le commit initial.
