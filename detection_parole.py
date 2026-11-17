"""
Détection de parole robuste au bruit ambiant (VAD à seuil adaptatif).

Problème mesuré sur les enregistrements de Pepper :
le ventilateur interne (dans la tête, près des micros) produit un
bruit constant vers 415 Hz et ses harmoniques, EN PLEIN dans la bande
de la voix, à un niveau proche de celui de la parole (-31 dB contre
environ -26 dB pour la voix). Un seuil sur l'énergie globale ne peut
donc pas séparer voix et bruit.

Principe retenu : rapport signal/bruit spectral « blanchi »

1. Le signal est découpé en trames de 20 ms ; une FFT donne la
   puissance de chaque trame pour chaque fréquence de la bande vocale
   (300-3400 Hz, résolution 50 Hz).
2. Un PROFIL DE BRUIT est estimé fréquence par fréquence :
   - calibration au démarrage sur quelques secondes sans parole ;
   - puis suivi adaptatif après chaque enregistrement, à partir des
     trames sans parole (descente rapide, montée lente).
3. Pour chaque trame, chaque fréquence est comparée à SON propre
   niveau de bruit (rapport en dB), puis on fait la moyenne sur toutes
   les fréquences. Les fréquences du ventilateur, déjà très fortes dans
   le bruit, ne dominent plus : la voix, qui ajoute de l'énergie sur
   toute la bande, ressort nettement.
4. Ce rapport est lissé sur 100 ms (une syllabe) pour réduire les
   fluctuations aléatoires du bruit.
5. Une trame est « voisée » si ce rapport dépasse SEUIL_SNR_DB.
   Ce seuil étant relatif au bruit mesuré, il s'adapte
   automatiquement à la salle (seuil adaptatif).
6. Lissage des décisions : les courtes pauses entre mots sont
   comblées, les impulsions brèves (claquement, choc, pas) supprimées.
7. Décision finale : assez de parole au total, et assez forte.

Mesures de réglage (bruit = ventilateur de Pepper) :
    ventilateur seul           : rapport max  1,9 dB  -> rejeté
    vraie parole devant Pepper : rapport 3 à 7,5 dB   -> accepté
    voix atténuée de 10 dB     : médiane 0,8 dB       -> rejeté
    voix atténuée de 26 dB     : médiane -0,8 dB      -> rejeté

Test hors ligne :
    python detection_parole.py fichier1.wav [fichier2.wav ...]
    python detection_parole.py --bruit silence.wav fichier.wav ...
"""

import sys
import wave

import numpy as np


# ==========================================
# PARAMÈTRES (à ajuster sur le vrai robot)
# ==========================================

TRAME_MS = 20

BANDE_VOIX_HZ = (300.0, 3400.0)

# Lissage temporel du rapport signal/bruit (5 x 20 ms = 100 ms).
LISSAGE_TRAMES = 5

# Rapport signal/bruit moyen (dB) au-dessus duquel une trame est
# considérée comme de la parole. Augmenter si du bruit passe,
# diminuer si Pepper n'entend pas une personne proche.
SEUIL_SNR_DB = 3.0

# Pauses entre mots comblées si plus courtes que ceci.
PAUSE_MAX_MS = 300

# Segments voisés plus courts que ceci = bruit impulsionnel.
SEGMENT_MIN_MS = 200

# Durée totale de parole nécessaire pour valider l'enregistrement.
PAROLE_MIN_MS = 400

# Modulation minimale (écart-type du niveau, en dB) des trames
# détectées. La voix varie au rythme des syllabes ; un bruit stable
# qui vient d'augmenter (ventilateur qui accélère) ne varie pas.
# Mesuré : bruit stable 1,8 dB, parole 2,7 à 5,6 dB.
MODULATION_MIN_DB = 2.3

# Niveau absolu minimal (médiane, en dB) des trames de parole.
# Garde-fou pour une salle très silencieuse, où même une voix
# lointaine aurait un bon rapport signal/bruit.
NIVEAU_MIN_DB = -45.0

# Suivi du profil de bruit : descente rapide, montée lente
# (un enregistrement entièrement parlé ne doit pas « apprendre »
# la voix comme du bruit).
ALPHA_DESCENTE = 0.5
ALPHA_MONTEE = 0.05

# Apprentissage rapide quand l'enregistrement est jugé
# entièrement composé de bruit stable.
ALPHA_BRUIT_STABLE = 0.5

# Seules les trames NETTEMENT sous le seuil servent à apprendre
# le bruit (évite d'apprendre les fins de phrases faibles).
MARGE_APPRENTISSAGE_DB = 1.5

# Sans calibration : part des trames les plus calmes utilisée pour
# estimer le bruit dans l'enregistrement lui-même.
PART_TRAMES_CALMES = 0.3


# ==========================================
# LECTURE WAV
# ==========================================

def lire_wav(chemin):
    """Retourne (signal float32 mono dans [-1, 1], fréquence)."""

    with wave.open(chemin, "rb") as f:
        n_canaux = f.getnchannels()
        largeur = f.getsampwidth()
        frequence = f.getframerate()
        brut = f.readframes(f.getnframes())

    if largeur == 2:
        signal = np.frombuffer(brut, dtype="<i2").astype(np.float32)
        signal /= 32768.0
    elif largeur == 4:
        signal = np.frombuffer(brut, dtype="<i4").astype(np.float32)
        signal /= 2147483648.0
    elif largeur == 1:
        signal = np.frombuffer(brut, dtype=np.uint8).astype(np.float32)
        signal = (signal - 128.0) / 128.0
    else:
        raise ValueError("Format WAV non supporté ({} octets)".format(largeur))

    if n_canaux > 1:
        signal = signal.reshape(-1, n_canaux).mean(axis=1)

    # Retirer une éventuelle composante continue du micro.
    if signal.size:
        signal = signal - signal.mean()

    return signal, frequence


# ==========================================
# SPECTRE TRAME PAR TRAME
# ==========================================

def spectre_trames(signal, frequence):
    """
    Retourne la puissance (trames x fréquences) limitée à la bande
    vocale, normalisée pour qu'une sinusoïde pleine échelle ≈ 0 dB.
    """

    taille = int(frequence * TRAME_MS / 1000)
    n_trames = len(signal) // taille

    freqs = np.fft.rfftfreq(taille, 1.0 / frequence)
    bande = (freqs >= BANDE_VOIX_HZ[0]) & (freqs <= BANDE_VOIX_HZ[1])

    if n_trames == 0:
        return np.zeros((0, int(bande.sum())))

    trames = signal[:n_trames * taille].reshape(n_trames, taille)
    fenetre = np.hanning(taille).astype(np.float32)

    puissance = np.abs(np.fft.rfft(trames * fenetre, axis=1)) ** 2
    puissance /= (fenetre.sum() ** 2) / 4.0

    return puissance[:, bande]


def lisser_temps(puissance):
    """Moyenne glissante de la puissance sur LISSAGE_TRAMES trames."""

    if puissance.shape[0] == 0:
        return puissance

    noyau = np.ones(LISSAGE_TRAMES) / LISSAGE_TRAMES
    cumul = np.apply_along_axis(
        lambda colonne: np.convolve(colonne, noyau, mode="same"),
        0, puissance)
    return cumul


def en_db(x):
    return 10.0 * np.log10(x + 1e-12)


def estimer_bruit(puissance, part=1.0):
    """
    Profil de bruit = moyenne, par fréquence, des trames les plus
    calmes (on écarte les trames les plus énergiques, qui peuvent
    contenir un bruit ponctuel ou de la parole).
    """

    energie = puissance.sum(axis=1)
    n = max(1, int(round(len(energie) * part)))
    calmes = np.argsort(energie)[:n]
    return puissance[calmes].mean(axis=0)


# ==========================================
# LISSAGE DES DÉCISIONS
# ==========================================

def _segments(masque):
    """Liste des (début, fin) des suites de True."""

    segments = []
    debut = None

    for i, v in enumerate(masque):
        if v and debut is None:
            debut = i
        elif not v and debut is not None:
            segments.append((debut, i))
            debut = None

    if debut is not None:
        segments.append((debut, len(masque)))

    return segments


def lisser_decisions(masque):
    """Comble les courtes pauses puis supprime les impulsions brèves."""

    masque = masque.copy()
    pause_max = int(PAUSE_MAX_MS / TRAME_MS)
    segment_min = int(SEGMENT_MIN_MS / TRAME_MS)

    # 1. Supprimer les impulsions isolées trop courtes.
    for debut, fin in _segments(masque):
        if fin - debut < segment_min // 2:
            masque[debut:fin] = False

    # 2. Combler les pauses courtes entre deux segments voisés.
    segs = _segments(masque)
    for (_, fin_a), (debut_b, _) in zip(segs, segs[1:]):
        if debut_b - fin_a <= pause_max:
            masque[fin_a:debut_b] = True

    # 3. Supprimer les segments restants trop courts.
    for debut, fin in _segments(masque):
        if fin - debut < segment_min:
            masque[debut:fin] = False

    return masque


# ==========================================
# DÉTECTEUR AVEC PROFIL DE BRUIT ADAPTATIF
# ==========================================

class DetecteurParole(object):

    def __init__(self):
        # Puissance moyenne du bruit pour chaque fréquence de la
        # bande vocale. None = pas encore calibré.
        self.profil_bruit = None
        self.frequence = None

    # ------------------------------------------

    def niveau_bruit_db(self):
        if self.profil_bruit is None:
            return None
        return round(float(en_db(self.profil_bruit.sum())), 1)

    # ------------------------------------------

    def calibrer(self, chemin_wav):
        """
        Apprend le profil du bruit ambiant sur un enregistrement
        fait SANS parole (Pepper et la salle « au repos »).
        Retourne le niveau de bruit en dB.
        """

        return self.calibrer_signal(*lire_wav(chemin_wav))

    def calibrer_signal(self, signal, frequence):
        """Comme calibrer(), à partir d'un signal en mémoire."""

        puissance = spectre_trames(signal, frequence)

        if puissance.shape[0] == 0:
            return self.niveau_bruit_db()

        # On écarte les 10 % de trames les plus fortes
        # (petit bruit ponctuel pendant la calibration).
        self.profil_bruit = estimer_bruit(puissance, part=0.9)
        self.frequence = frequence

        return self.niveau_bruit_db()

    # ------------------------------------------

    def _mettre_a_jour_bruit(self, puissance, masque_voix, snr_db,
                             bruit_stable=False):
        """Suivi du bruit ambiant à partir des trames sans parole."""

        if bruit_stable:
            # Tout l'enregistrement est du bruit stable :
            # on l'apprend rapidement comme nouveau bruit de fond.
            estimation = puissance.mean(axis=0)
            a = ALPHA_BRUIT_STABLE
            self.profil_bruit = (1 - a) * self.profil_bruit + a * estimation
            return

        # Marge de sécurité : on écarte aussi les trames voisines
        # de la parole (début et fin de mots).
        marge = LISSAGE_TRAMES
        proche_voix = np.convolve(
            masque_voix.astype(float), np.ones(2 * marge + 1), mode="same") > 0

        calmes = (~proche_voix) & (snr_db < SEUIL_SNR_DB - MARGE_APPRENTISSAGE_DB)
        bruit = puissance[calmes]
        if bruit.shape[0] < 25:
            # Moins de 0,5 s sans parole : on n'apprend rien,
            # pour ne pas confondre voix et bruit.
            return

        estimation = bruit.mean(axis=0)

        # Par fréquence : descente rapide, montée lente.
        alpha = np.where(estimation < self.profil_bruit,
                         ALPHA_DESCENTE, ALPHA_MONTEE)
        self.profil_bruit = (1 - alpha) * self.profil_bruit + alpha * estimation

    # ------------------------------------------

    def analyser(self, chemin_wav, mettre_a_jour=True):
        """
        Analyse un enregistrement.
        Retourne un dict avec 'parole' (bool), 'raison' et des mesures.
        """

        signal, frequence = lire_wav(chemin_wav)
        return self.analyser_signal(signal, frequence, mettre_a_jour)

    def analyser_signal(self, signal, frequence, mettre_a_jour=True):
        """Comme analyser(), à partir d'un signal en mémoire."""

        puissance = spectre_trames(signal, frequence)

        if puissance.shape[0] == 0:
            return {"parole": False, "raison": "enregistrement vide"}

        if self.profil_bruit is None or self.frequence != frequence:
            # Pas de calibration utilisable : estimation du bruit sur
            # les moments les plus calmes de l'enregistrement.
            self.profil_bruit = estimer_bruit(puissance, PART_TRAMES_CALMES)
            self.frequence = frequence

        # Rapport signal/bruit blanchi : chaque fréquence comparée
        # à son propre bruit, puis moyenne sur la bande vocale.
        lissee = lisser_temps(puissance)
        snr_db = np.mean(en_db(lissee) - en_db(self.profil_bruit), axis=1)

        masque = lisser_decisions(snr_db > SEUIL_SNR_DB)

        duree_parole_ms = int(masque.sum()) * TRAME_MS
        if masque.any():
            niveau_parole_db = float(np.median(en_db(lissee[masque].sum(axis=1))))
            snr_parole_db = float(np.median(snr_db[masque]))
            # Variation du niveau (non lissé) pendant la « parole ».
            modulation_db = float(np.std(en_db(puissance[masque].sum(axis=1))))
        else:
            niveau_parole_db = float("-inf")
            snr_parole_db = float(np.max(snr_db))
            modulation_db = 0.0

        resultat = {
            "bruit_db": self.niveau_bruit_db(),
            "duree_parole_ms": duree_parole_ms,
            "niveau_parole_db": round(niveau_parole_db, 1),
            "snr_db": round(snr_parole_db, 1),
            "modulation_db": round(modulation_db, 1),
        }

        bruit_stable = False

        if duree_parole_ms < PAROLE_MIN_MS:
            resultat["parole"] = False
            resultat["raison"] = "silence ou bruit seul ({} ms de parole < {} ms)".format(
                duree_parole_ms, PAROLE_MIN_MS)
        elif modulation_db < MODULATION_MIN_DB:
            bruit_stable = True
            resultat["parole"] = False
            resultat["raison"] = "bruit stable, pas de parole (modulation {:.1f} dB < {:.1f} dB)".format(
                modulation_db, MODULATION_MIN_DB)
        elif niveau_parole_db < NIVEAU_MIN_DB:
            resultat["parole"] = False
            resultat["raison"] = "voix trop faible / trop lointaine ({:.1f} dB < {:.1f} dB)".format(
                niveau_parole_db, NIVEAU_MIN_DB)
        else:
            resultat["parole"] = True
            resultat["raison"] = "parole détectée"

        if mettre_a_jour:
            self._mettre_a_jour_bruit(puissance, masque, snr_db, bruit_stable)

        return resultat


# ==========================================
# ÉCOUTE EN CONTINU (TEMPS RÉEL)
# ==========================================

# Il faut SEUIL dépassé pendant ce temps pour commencer à écouter
# (un bruit bref ne déclenche rien).
DEBUT_MS = 200

# Audio conservé AVANT le déclenchement, pour ne pas couper
# le début du premier mot.
PRE_ROLL_MS = 500

# Silence nécessaire pour considérer que la personne a fini.
FIN_SILENCE_MS = 900

# Durée maximale d'une prise de parole.
PAROLE_MAX_S = 15

# Fin de parole : sur les FIN_SILENCE_MS dernières millisecondes,
# au plus cette part de trames au-dessus du seuil
# (tolère quelques pics de bruit isolés).
PART_VOIX_FIN = 0.15

# Suivi du bruit pendant l'attente, trame par trame : moyenne
# glissante symétrique (non biaisée), constante de temps ~2 s.
ALPHA_FLUX = 0.01


class EcouteContinue(object):
    """
    Reçoit le flux audio du micro par morceaux et découpe
    automatiquement les prises de parole.

    États :
      - « attente » : on écoute le bruit ambiant (et on l'apprend) ;
        si la voix dépasse le seuil pendant DEBUT_MS -> « parole ».
      - « parole »  : on accumule le son ; après FIN_SILENCE_MS de
        silence (ou PAROLE_MAX_S), la prise de parole est terminée
        et renvoyée par ajouter().
    """

    def __init__(self, detecteur, frequence=16000):
        from collections import deque

        self.detecteur = detecteur
        self.frequence = frequence
        self.taille = int(frequence * TRAME_MS / 1000)

        self._deque = deque
        self.n_debut = int(DEBUT_MS / TRAME_MS)
        self.n_fin = int(FIN_SILENCE_MS / TRAME_MS)
        self.n_max = int(PAROLE_MAX_S * 1000 / TRAME_MS)
        self.n_pre = int(PRE_ROLL_MS / TRAME_MS)

        self.reinitialiser()

    # ------------------------------------------

    def reinitialiser(self):
        """Oublie tout l'audio en cours (après que Pepper a parlé)."""

        self.reste = np.zeros(0, dtype=np.float32)
        self.historique = self._deque(maxlen=LISSAGE_TRAMES)
        self.pre_roll = self._deque(maxlen=self.n_pre)
        self.segment = []
        self.en_parole = False
        self.n_voix = 0
        self.fenetre_fin = self._deque(maxlen=self.n_fin)
        self.dernier_snr_db = 0.0

    # ------------------------------------------

    def ajouter(self, echantillons):
        """
        Ajoute des échantillons (float32 dans [-1, 1]).
        Retourne la liste des prises de parole terminées
        (chacune est un signal numpy).
        """

        termines = []

        x = np.concatenate([self.reste, echantillons.astype(np.float32)])
        n = len(x) // self.taille
        self.reste = x[n * self.taille:]

        for i in range(n):
            trame = x[i * self.taille:(i + 1) * self.taille]
            fini = self._traiter_trame(trame)
            if fini is not None:
                termines.append(fini)

        return termines

    # ------------------------------------------

    def _traiter_trame(self, trame):

        det = self.detecteur
        puissance = spectre_trames(trame, self.frequence)[0]

        if det.profil_bruit is None:
            det.profil_bruit = puissance.copy()
            det.frequence = self.frequence

        # Rapport signal/bruit blanchi, lissé sur LISSAGE_TRAMES.
        self.historique.append(puissance)
        lissee = np.mean(self.historique, axis=0)
        snr = float(np.mean(en_db(lissee) - en_db(det.profil_bruit)))
        self.dernier_snr_db = snr
        voix = snr > SEUIL_SNR_DB

        if not self.en_parole:

            self.pre_roll.append(trame)

            # Apprentissage continu du bruit sur les trames calmes.
            if snr < SEUIL_SNR_DB - MARGE_APPRENTISSAGE_DB:
                det.profil_bruit = ((1 - ALPHA_FLUX) * det.profil_bruit
                                    + ALPHA_FLUX * puissance)

            self.n_voix = self.n_voix + 1 if voix else 0

            if self.n_voix >= self.n_debut:
                # Début de la prise de parole (avec le pré-roll).
                self.en_parole = True
                self.segment = list(self.pre_roll)
                self.pre_roll.clear()
                self.fenetre_fin.clear()

            return None

        # En cours de parole.
        self.segment.append(trame)
        self.fenetre_fin.append(voix)

        silence = (len(self.fenetre_fin) == self.n_fin
                   and sum(self.fenetre_fin) <= PART_VOIX_FIN * self.n_fin)

        if silence or len(self.segment) >= self.n_max:
            signal = np.concatenate(self.segment)
            self.segment = []
            self.en_parole = False
            self.n_voix = 0
            self.fenetre_fin.clear()
            return signal

        return None


# ==========================================
# TEST HORS LIGNE
# ==========================================

if __name__ == "__main__":

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)

    fichier_bruit = None
    if args[0] == "--bruit":
        fichier_bruit = args[1]
        args = args[2:]

    for chemin in args:
        # Chaque fichier est analysé indépendamment.
        detecteur = DetecteurParole()
        if fichier_bruit:
            detecteur.calibrer(fichier_bruit)
        r = detecteur.analyser(chemin, mettre_a_jour=False)
        print("{:<24} {:<5} {}".format(
            chemin.split("/")[-1], "OUI" if r["parole"] else "non", r))
