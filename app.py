"""
AcademieIA - demo d'interface unifiee
- Connexion / Inscription (avec champ "profession")
- Tableau de bord admin
- Tableau de bord super_admin (gestion des admins + vue globale)

Cette version utilise des donnees fictives en memoire (st.session_state)
pour la demo. Les blocs marques "# --- SUPABASE ---" indiquent ou brancher
les vraies requetes Supabase (table users, table admins) a la place.
"""

import streamlit as st
import pandas as pd
import hashlib
import json
import secrets
import string
from datetime import date, datetime

try:
    from supabase import create_client
except ImportError:
    create_client = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

PDF_ACTIF = FPDF is not None


def _texte_pdf_securise(texte):
    """Le moteur PDF (police standard) ne gere que le latin-1 : on retire
    proprement les caracteres non supportes (emojis, etc.) plutot que de planter."""
    return (texte or "").encode("latin-1", errors="ignore").decode("latin-1")


def generer_pdf_texte(titre, corps):
    """Genere un PDF simple (titre + corps de texte) et retourne les octets."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.multi_cell(0, 10, _texte_pdf_securise(titre))
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 7, _texte_pdf_securise(corps))
    sortie = pdf.output(dest="S")
    if isinstance(sortie, str):
        sortie = sortie.encode("latin-1")
    return bytes(sortie)


def generer_pdf_certificat(nom_utilisateur, profession):
    """Genere le certificat PDF de fin de parcours (Niveau 4 termine)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=22)
    pdf.ln(20)
    pdf.multi_cell(0, 14, _texte_pdf_securise("Certificat de Maitrise AcademieIA"), align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=14)
    pdf.multi_cell(
        0, 10,
        _texte_pdf_securise(
            f"Ce certificat est decerne a\n\n{nom_utilisateur}\n\n"
            f"pour avoir termine avec succes le parcours AcademieIA\n"
            f"d'apprentissage de l'intelligence artificielle applique au metier de {profession}."
        ),
        align="C",
    )
    pdf.ln(14)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 7, _texte_pdf_securise(f"Delivre le {date.today().strftime('%d/%m/%Y')}"), align="C")
    sortie = pdf.output(dest="S")
    if isinstance(sortie, str):
        sortie = sortie.encode("latin-1")
    return bytes(sortie)

# ----------------------------------------------------------------------
# Connexion Groq (assistant IA)
# ----------------------------------------------------------------------
# Groq offre une API gratuite (avec quota) compatible avec des modeles Llama.
# Cle a obtenir gratuitement sur https://console.groq.com/keys
#
# Secret attendu dans .streamlit/secrets.toml (ou secrets Streamlit Cloud) :
#   GROQ_API_KEY = "gsk_..."
#
# Si absent, l'assistant reste en mode demo (message d'explication).
GROQ_ACTIF = Groq is not None and "GROQ_API_KEY" in st.secrets


@st.cache_resource
def get_client_groq():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


def repondre_assistant_ia(question, profession, niveaux_debloques):
    """Interroge Groq (modele Llama gratuit) avec un contexte adapte au metier de l'utilisateur."""
    client = get_client_groq()
    contexte_metier = profession or "un metier technique"
    contexte_niveaux = ", ".join(niveaux_debloques) if niveaux_debloques else "aucun niveau debloque"
    prompt_systeme = (
        f"Tu es l'assistant pedagogique d'AcademieIA, une plateforme qui apprend a des "
        f"professionnels de tous les metiers a utiliser l'intelligence artificielle dans "
        f"leur travail quotidien. L'utilisateur exerce le metier suivant : {contexte_metier}. "
        f"Il a acces aux niveaux suivants : {contexte_niveaux}. Reponds de facon claire, concrete "
        f"et pratique, avec des exemples adaptes a son metier, pour lui montrer comment l'IA peut "
        f"concretement l'aider au quotidien. Reponds en francais."
    )
    reponse = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": prompt_systeme},
            {"role": "user", "content": question},
        ],
        max_tokens=800,
    )
    return reponse.choices[0].message.content


def repondre_aide_appli(question):
    """Interroge Groq avec un contexte fixe decrivant le fonctionnement d'AcademieIA,
    pour aider l'utilisateur a naviguer et comprendre l'appli (pas ses questions de metier)."""
    client = get_client_groq()
    prompt_systeme = (
        "Tu es le guide d'utilisation de l'application AcademieIA. Tu ne reponds PAS aux questions "
        "de metier (ca c'est le role de l'Assistant IA de l'appli) : tu expliques uniquement comment "
        "utiliser AcademieIA elle-meme. Voici comment l'appli fonctionne :\n\n"
        "- L'appli a 4 niveaux payants et progressifs (Niveau 1 a 4), chacun coute 5 000 FCFA.\n"
        "- Le Niveau 1 est gratuit et se termine en posant une premiere question a l'Assistant IA.\n"
        "- Pour debloquer un niveau superieur : payer via Wave au numero indique dans l'onglet "
        "'Mes niveaux', envoyer la preuve de paiement par WhatsApp a l'administrateur, attendre "
        "qu'il genere un code d'acces, puis saisir ce code dans l'onglet 'Mes niveaux'.\n"
        "- Chaque niveau debloque contient un quiz de validation (3 questions) : il faut tout "
        "reussir pour pouvoir debloquer le niveau suivant.\n"
        "- L'onglet 'Assistant IA' sert a poser des questions liees a son metier.\n"
        "- L'onglet 'Mes niveaux' montre la progression et permet de payer/debloquer.\n"
        "- L'onglet 'Historique' montre les questions deja posees a l'assistant.\n"
        "- L'onglet 'Support' sert a envoyer un message a un administrateur en cas de probleme.\n"
        "- A la fin du parcours (4 niveaux + quiz reussis), un certificat PDF est telechargeable.\n\n"
        "Reponds toujours en francais, de facon simple et courte, en expliquant concretement quel "
        "onglet ou quel bouton utiliser."
    )
    reponse = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": prompt_systeme},
            {"role": "user", "content": question},
        ],
        max_tokens=400,
    )
    return reponse.choices[0].message.content


def generer_progression_ia(matiere, niveau_classe, nb_semaines, extrait_programme=None):
    """Genere une progression annuelle via Groq, sous forme de liste de semaines."""
    client = get_client_groq()
    contexte_programme = (
        f"Voici un extrait du programme officiel a respecter :\n{extrait_programme}\n\n"
        if extrait_programme else
        "Aucun programme officiel fourni : propose une progression standard et coherente.\n\n"
    )
    prompt_systeme = (
        f"Tu es un conseiller pedagogique pour l'enseignement technique et professionnel. "
        f"Genere une progression annuelle pour la matiere '{matiere}', niveau '{niveau_classe}', "
        f"sur {nb_semaines} semaines. {contexte_programme}"
        f"Reponds UNIQUEMENT avec un tableau JSON valide, sans texte autour, au format exact :\n"
        f'[{{"semaine": 1, "theme": "...", "objectifs": "..."}}, ...]\n'
        f"Un objet par semaine, {nb_semaines} objets au total. Reponds en francais."
    )
    reponse = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": prompt_systeme},
            {"role": "user", "content": "Genere la progression."},
        ],
        max_tokens=4000,
    )
    texte = reponse.choices[0].message.content.strip()
    texte = texte.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(texte)


def generer_document_cours_devoir(type_document, matiere, niveau_classe, theme_semaine, objectifs):
    """Genere le cours ou le devoir d'une semaine donnee via Groq."""
    client = get_client_groq()
    if type_document == "cours":
        consigne = (
            "Redige un cours structure (objectifs pedagogiques, rappel de notions, deroule "
            "de la seance, exemples concrets adaptes au metier) pret a etre utilise par un enseignant."
        )
    else:
        consigne = (
            "Redige un devoir ou une serie d'exercices (enonces clairs et, si pertinent, "
            "un bareme indicatif) pour evaluer les eleves sur ce theme."
        )
    prompt_systeme = (
        f"Tu es un conseiller pedagogique pour l'enseignement technique et professionnel. "
        f"Matiere : {matiere}. Niveau : {niveau_classe}. Theme de la semaine : {theme_semaine}. "
        f"Objectifs : {objectifs}. {consigne} Reponds en francais, de facon claire et structuree."
    )
    reponse = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": prompt_systeme},
            {"role": "user", "content": f"Genere le {type_document}."},
        ],
        max_tokens=2000,
    )
    return reponse.choices[0].message.content

# ----------------------------------------------------------------------
# Connexion Supabase
# ----------------------------------------------------------------------
# Ta table "users" gere ses propres comptes (colonne password_hash, en SHA-256)
# plutot que le systeme Supabase Auth. Le code ci-dessous lit/ecrit donc
# directement dans cette table.
#
# Secrets attendus dans .streamlit/secrets.toml (ou secrets Streamlit Cloud) :
#   SUPABASE_URL = "https://xxxxx.supabase.co"
#   SUPABASE_ANON_KEY = "..."          # cle publique, suffisante ici car RLS
#                                        est actuellement desactive sur users
#
# Si ces secrets ne sont pas presents, l'appli reste en mode demo (donnees fictives).
SUPABASE_ACTIF = create_client is not None and "SUPABASE_URL" in st.secrets and "SUPABASE_ANON_KEY" in st.secrets


@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


def hasher_mot_de_passe(mot_de_passe):
    return hashlib.sha256(mot_de_passe.encode()).hexdigest()


def charger_niveaux_utilisateur(user_id):
    if not SUPABASE_ACTIF or not user_id:
        return []
    try:
        client = get_client()
        reponse = client.table("user_niveaux").select("niveau").eq("user_id", user_id).execute()
        return [ligne["niveau"] for ligne in reponse.data]
    except Exception:
        return []


def charger_progression_niveau1(user_id):
    """Charge la progression de l'utilisateur sur le Niveau 1 (nb de messages
    envoyes a l'assistant, et si le niveau est termine)."""
    if not SUPABASE_ACTIF or not user_id:
        return {"messages_envoyes_niveau1": 0, "niveau1_complete": False}
    try:
        client = get_client()
        reponse = client.table("users").select(
            "messages_envoyes_niveau1, niveau1_complete"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        return {
            "messages_envoyes_niveau1": donnees.get("messages_envoyes_niveau1") or 0,
            "niveau1_complete": bool(donnees.get("niveau1_complete")),
        }
    except Exception:
        return {"messages_envoyes_niveau1": 0, "niveau1_complete": False}


def enregistrer_message_niveau1(user_id, nombre_actuel):
    """Incremente le compteur de messages envoyes au Niveau 1. Des qu'un message
    libre a ete envoye, le niveau est marque comme termine."""
    if not SUPABASE_ACTIF or not user_id:
        return
    nouveau_nombre = (nombre_actuel or 0) + 1
    try:
        client = get_client()
        client.table("users").update({
            "messages_envoyes_niveau1": nouveau_nombre,
            "niveau1_complete": True,
        }).eq("id", user_id).execute()
    except Exception:
        pass


# ------------------------------------------------------------------------
# Quota quotidien de questions a l'assistant (selon le plus haut niveau
# debloque). None = illimite.
# ------------------------------------------------------------------------
QUOTAS_PAR_NIVEAU = {0: 3, 1: 8, 2: 20, 3: 50, 4: None}


def obtenir_quota_max(noms_debloques):
    """Retourne le quota de questions/jour selon le plus haut niveau debloque
    par l'utilisateur (0 = aucun niveau paye debloque). None = illimite."""
    niveau_max = 0
    for nom in noms_debloques or []:
        for numero in range(1, 5):
            if nom.startswith(f"Niveau {numero}"):
                niveau_max = max(niveau_max, numero)
    return QUOTAS_PAR_NIVEAU.get(niveau_max, 3)


def charger_quota_utilisateur(user_id):
    """Charge le compteur de questions du jour. Si la date enregistree n'est
    pas celle d'aujourd'hui, le compteur est considere comme remis a zero."""
    if not SUPABASE_ACTIF or not user_id:
        return 0
    try:
        client = get_client()
        reponse = client.table("users").select(
            "quota_questions_jour, quota_date"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        if donnees.get("quota_date") == date.today().isoformat():
            return donnees.get("quota_questions_jour") or 0
        return 0
    except Exception:
        return 0


def enregistrer_question_quota(user_id, questions_utilisees_aujourdhui):
    """Incremente le compteur de questions du jour (remet a 1 si on a change
    de jour depuis la derniere question)."""
    if not SUPABASE_ACTIF or not user_id:
        return
    nouveau_nombre = (questions_utilisees_aujourdhui or 0) + 1
    try:
        client = get_client()
        client.table("users").update({
            "quota_questions_jour": nouveau_nombre,
            "quota_date": date.today().isoformat(),
        }).eq("id", user_id).execute()
    except Exception:
        pass
# ------------------------------------------------------------------------


def charger_progression_niveau2(user_id):
    """Charge la progression du Niveau 2 : liste des prompts-modeles deja utilises
    (identifiants sous forme de texte separe par des virgules) et si le niveau est termine."""
    if not SUPABASE_ACTIF or not user_id:
        return {"prompts_utilises_niveau2": [], "niveau2_complete": False}
    try:
        client = get_client()
        reponse = client.table("users").select(
            "prompts_utilises_niveau2, niveau2_complete"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        texte = donnees.get("prompts_utilises_niveau2") or ""
        utilises = [valeur for valeur in texte.split(",") if valeur]
        return {
            "prompts_utilises_niveau2": utilises,
            "niveau2_complete": bool(donnees.get("niveau2_complete")),
        }
    except Exception:
        return {"prompts_utilises_niveau2": [], "niveau2_complete": False}


def enregistrer_prompt_niveau2(user_id, index_prompt, utilises_actuels):
    """Ajoute un prompt-modele a la liste de ceux deja essayes par l'utilisateur.
    Des que 3 prompts-modeles differents ont ete utilises, le niveau est termine."""
    if not SUPABASE_ACTIF or not user_id:
        return
    index_str = str(index_prompt)
    if index_str in utilises_actuels:
        return
    nouveaux = utilises_actuels + [index_str]
    complete = len(set(nouveaux)) >= 3
    try:
        client = get_client()
        client.table("users").update({
            "prompts_utilises_niveau2": ",".join(nouveaux),
            "niveau2_complete": complete,
        }).eq("id", user_id).execute()
    except Exception:
        pass


def charger_progression_niveau3(user_id):
    """Charge la progression du Niveau 3 : nb d'echanges libres envoyes et si termine."""
    if not SUPABASE_ACTIF or not user_id:
        return {"messages_envoyes_niveau3": 0, "niveau3_complete": False}
    try:
        client = get_client()
        reponse = client.table("users").select(
            "messages_envoyes_niveau3, niveau3_complete"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        return {
            "messages_envoyes_niveau3": donnees.get("messages_envoyes_niveau3") or 0,
            "niveau3_complete": bool(donnees.get("niveau3_complete")),
        }
    except Exception:
        return {"messages_envoyes_niveau3": 0, "niveau3_complete": False}


def enregistrer_message_niveau3(user_id, nombre_actuel):
    """Incremente le compteur d'echanges libres du Niveau 3. Termine des que 5 echanges
    ont ete envoyes (le critere 'au moins 1 reformulation' est traite cote UI)."""
    if not SUPABASE_ACTIF or not user_id:
        return
    nouveau_nombre = (nombre_actuel or 0) + 1
    complete = nouveau_nombre >= 5
    try:
        client = get_client()
        client.table("users").update({
            "messages_envoyes_niveau3": nouveau_nombre,
            "niveau3_complete": complete,
        }).eq("id", user_id).execute()
    except Exception:
        pass


def charger_progression_niveau4(user_id):
    """Charge la progression du Niveau 4 : cas d'usage avances deja essayes."""
    if not SUPABASE_ACTIF or not user_id:
        return {"prompts_utilises_niveau4": [], "niveau4_complete": False}
    try:
        client = get_client()
        reponse = client.table("users").select(
            "prompts_utilises_niveau4, niveau4_complete"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        texte = donnees.get("prompts_utilises_niveau4") or ""
        utilises = [valeur for valeur in texte.split(",") if valeur]
        return {
            "prompts_utilises_niveau4": utilises,
            "niveau4_complete": bool(donnees.get("niveau4_complete")),
        }
    except Exception:
        return {"prompts_utilises_niveau4": [], "niveau4_complete": False}


def enregistrer_prompt_niveau4(user_id, index_prompt, utilises_actuels):
    """Ajoute un cas d'usage avance a la liste de ceux deja essayes. Termine a 3 essayes."""
    if not SUPABASE_ACTIF or not user_id:
        return
    index_str = str(index_prompt)
    if index_str in utilises_actuels:
        return
    nouveaux = utilises_actuels + [index_str]
    complete = len(set(nouveaux)) >= 3
    try:
        client = get_client()
        client.table("users").update({
            "prompts_utilises_niveau4": ",".join(nouveaux),
            "niveau4_complete": complete,
        }).eq("id", user_id).execute()
    except Exception:
        pass


def charger_messages_utilisateur(user_id):
    """Charge tout le fil de discussion support d'un utilisateur, du plus ancien au plus recent."""
    if not SUPABASE_ACTIF or not user_id:
        return []
    try:
        client = get_client()
        reponse = client.table("messages_support").select("*").eq(
            "user_id", user_id
        ).order("cree_le").execute()
        return reponse.data or []
    except Exception:
        return []


def limiter_messages_support(user_id, max_messages=4):
    """Ne garde que les max_messages messages support les plus recents pour un utilisateur,
    en supprimant les plus anciens au-dela de cette limite."""
    if not SUPABASE_ACTIF or not user_id:
        return
    try:
        client = get_client()
        reponse = client.table("messages_support").select("id").eq(
            "user_id", user_id
        ).order("cree_le", desc=True).execute()
        ids = [ligne["id"] for ligne in (reponse.data or [])]
        ids_a_supprimer = ids[max_messages:]
        if ids_a_supprimer:
            client.table("messages_support").delete().in_("id", ids_a_supprimer).execute()
    except Exception:
        pass


def envoyer_message_support(user_id, auteur, contenu):
    """Ajoute un message dans le fil de discussion support d'un utilisateur, puis ne garde
    que les 4 derniers messages de ce fil (les plus anciens sont supprimes automatiquement).
    auteur : 'utilisateur' si envoye par l'utilisateur, sinon le nom de l'admin."""
    if not SUPABASE_ACTIF or not user_id or not contenu:
        return
    try:
        client = get_client()
        client.table("messages_support").insert({
            "user_id": user_id,
            "auteur": auteur,
            "contenu": contenu,
        }).execute()
        limiter_messages_support(user_id)
    except Exception:
        pass


def limiter_historique_questions(user_id, max_echanges=4):
    """Ne garde que les max_echanges echanges d'historique les plus recents pour un utilisateur,
    en supprimant les plus anciens au-dela de cette limite."""
    if not SUPABASE_ACTIF or not user_id:
        return
    try:
        client = get_client()
        reponse = client.table("historique_questions").select("id").eq(
            "user_id", user_id
        ).order("cree_le", desc=True).execute()
        ids = [ligne["id"] for ligne in (reponse.data or [])]
        ids_a_supprimer = ids[max_echanges:]
        if ids_a_supprimer:
            client.table("historique_questions").delete().in_("id", ids_a_supprimer).execute()
    except Exception:
        pass


def enregistrer_historique_question(user_id, question, reponse):
    """Enregistre un echange question/reponse avec l'assistant IA dans l'historique, puis ne
    garde que les 4 derniers echanges (les plus anciens sont supprimes automatiquement)."""
    if not SUPABASE_ACTIF or not user_id:
        return
    try:
        client = get_client()
        client.table("historique_questions").insert({
            "user_id": user_id,
            "question": question,
            "reponse": reponse,
        }).execute()
        limiter_historique_questions(user_id)
    except Exception:
        pass


def charger_historique_utilisateur(user_id, limite=20):
    """Charge les derniers echanges question/reponse de l'utilisateur, du plus recent au plus ancien."""
    if not SUPABASE_ACTIF or not user_id:
        return []
    try:
        client = get_client()
        reponse = client.table("historique_questions").select("*").eq(
            "user_id", user_id
        ).order("cree_le", desc=True).limit(limite).execute()
        return reponse.data or []
    except Exception:
        return []


def charger_statistiques_globales():
    """Charge des statistiques d'usage globales pour le tableau de bord admin :
    nombre total de questions posees, et nombre d'utilisateurs ayant termine chaque niveau."""
    if not SUPABASE_ACTIF:
        return {"total_questions": 0, "niveau1_complete": 0, "niveau2_complete": 0, "niveau3_complete": 0, "niveau4_complete": 0}
    try:
        client = get_client()
        total_questions = client.table("historique_questions").select("id", count="exact").execute().count or 0
        reponse_niveaux = client.table("users").select(
            "niveau1_complete, niveau2_complete, niveau3_complete, niveau4_complete"
        ).eq("role", "utilisateur").execute()
        lignes = reponse_niveaux.data or []
        return {
            "total_questions": total_questions,
            "niveau1_complete": sum(1 for l in lignes if l.get("niveau1_complete")),
            "niveau2_complete": sum(1 for l in lignes if l.get("niveau2_complete")),
            "niveau3_complete": sum(1 for l in lignes if l.get("niveau3_complete")),
            "niveau4_complete": sum(1 for l in lignes if l.get("niveau4_complete")),
        }
    except Exception:
        return {"total_questions": 0, "niveau1_complete": 0, "niveau2_complete": 0, "niveau3_complete": 0, "niveau4_complete": 0}


def charger_conversations_admin():
    """Regroupe tous les messages support par utilisateur, avec le dernier message
    et son horodatage, pour affichage dans le dashboard admin."""
    if not SUPABASE_ACTIF:
        return []
    try:
        client = get_client()
        reponse = client.table("messages_support").select("*").order("cree_le", desc=True).execute()
        messages = reponse.data or []
        conversations = {}
        for message in messages:
            uid = message["user_id"]
            if uid not in conversations:
                conversations[uid] = {
                    "user_id": uid,
                    "dernier_message": message["contenu"],
                    "dernier_auteur": message["auteur"],
                    "dernier_horodatage": message["cree_le"],
                }
        return list(conversations.values())
    except Exception:
        return []


def soumettre_demande_paiement(user_id, niveau, reference):
    client = get_client()
    client.table("demandes_paiement").insert({
        "user_id": user_id,
        "niveau": niveau,
        "reference": reference or "-",
        "statut": "en_attente",
        "created_at": datetime.now().isoformat(),
    }, returning="minimal").execute()


def valider_code_acces(code, user_id):
    client = get_client()
    resultat = client.rpc("valider_code_acces", {"p_code": code, "p_user_id": user_id}).execute()
    valeur = resultat.data
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else None
    return valeur


def charger_utilisateurs_depuis_supabase():
    client = get_client()
    reponse = client.table("users").select("id, username, email, nom, profession, role, created_at").execute()
    df = pd.DataFrame(reponse.data)
    if df.empty:
        return df
    if "created_at" in df.columns:
        df = df.rename(columns={"created_at": "inscrit_le"})
    if "nom" not in df.columns:
        df["nom"] = None
    if "profession" not in df.columns:
        df["profession"] = None
    df["nom"] = df["nom"].fillna(df["username"])
    df["profession"] = df["profession"].fillna("-")
    df["role"] = df["role"].fillna("utilisateur")
    return df


def charger_demandes_paiement(statut=None):
    """Charge les demandes de paiement depuis Supabase (eventuellement filtrees par statut)."""
    if not SUPABASE_ACTIF:
        return pd.DataFrame()
    client = get_client()
    requete = client.table("demandes_paiement").select(
        "id, user_id, niveau, reference, statut, created_at, code_genere"
    )
    if statut:
        requete = requete.eq("statut", statut)
    reponse = requete.order("created_at", desc=True).execute()
    return pd.DataFrame(reponse.data)


def generer_code_acces():
    """Genere un code d'acces aleatoire lisible, du type ABCD-1234."""
    alphabet = string.ascii_uppercase + string.digits
    groupes = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)]
    return "-".join(groupes)


def approuver_demande_paiement(demande_id, niveau, code, user_id=None):
    """Cree le code d'acces pour le niveau demande et marque la demande comme approuvee.
    Marque aussi les autres demandes en attente du meme utilisateur comme obsoletes."""
    client = get_client()
    client.table("codes_acces").insert({
        "code": code,
        "niveau": niveau,
        "utilise": 0,
        "cree_le": str(date.today()),
        "created_at": datetime.now().isoformat(),
    }, returning="minimal").execute()
    client.table("demandes_paiement").update({
        "statut": "approuvee",
        "code_genere": code,
    }).eq("id", demande_id).execute()
    if user_id is not None:
        (
            client.table("demandes_paiement")
            .update({"statut": "obsolete"})
            .eq("user_id", user_id)
            .eq("statut", "en_attente")
            .neq("id", demande_id)
            .execute()
        )


def rejeter_demande_paiement(demande_id, user_id=None):
    client = get_client()
    client.table("demandes_paiement").update({"statut": "rejetee"}).eq("id", demande_id).execute()
    if user_id is not None:
        (
            client.table("demandes_paiement")
            .update({"statut": "obsolete"})
            .eq("user_id", user_id)
            .eq("statut", "en_attente")
            .neq("id", demande_id)
            .execute()
        )


def supprimer_compte(user_id):
    """Supprime definitivement un compte (utilisateur ou admin) et ses donnees liees."""
    client = get_client()
    client.table("demandes_paiement").delete().eq("user_id", user_id).execute()
    client.table("user_niveaux").delete().eq("user_id", user_id).execute()
    client.table("users").delete().eq("id", user_id).execute()


def charger_profil_enseignant(user_id):
    if not SUPABASE_ACTIF or not user_id:
        return None
    try:
        client = get_client()
        reponse = client.table("teacher_profiles").select("*").eq("id", user_id).execute()
        return reponse.data[0] if reponse.data else None
    except Exception:
        return None


def enregistrer_profil_enseignant(user_id, matiere, niveau_classe, etablissement, nb_semaines, programme_url=None):
    client = get_client()
    client.table("teacher_profiles").upsert({
        "id": user_id,
        "matiere": matiere,
        "niveau_classe": niveau_classe,
        "etablissement": etablissement,
        "nb_semaines": nb_semaines,
        "programme_officiel_url": programme_url,
    }).execute()


def uploader_programme_pdf(user_id, fichier_pdf):
    client = get_client()
    chemin = f"programmes/{user_id}_{fichier_pdf.name}"
    client.storage.from_("documents").upload(chemin, fichier_pdf.getvalue(), {"upsert": "true"})
    return chemin


def enregistrer_progression(teacher_id, contenu):
    client = get_client()
    reponse = client.table("progressions").insert({
        "teacher_id": teacher_id,
        "annee_scolaire": f"{date.today().year}-{date.today().year + 1}",
        "contenu": contenu,
    }).execute()
    return reponse.data[0] if reponse.data else None


def charger_derniere_progression(teacher_id):
    if not SUPABASE_ACTIF or not teacher_id:
        return None
    try:
        client = get_client()
        reponse = (
            client.table("progressions").select("*").eq("teacher_id", teacher_id)
            .order("created_at", desc=True).limit(1).execute()
        )
        return reponse.data[0] if reponse.data else None
    except Exception:
        return None


def charger_document_genere(teacher_id, progression_id, semaine, type_document):
    if not SUPABASE_ACTIF:
        return None
    try:
        client = get_client()
        reponse = (
            client.table("documents_generes").select("*")
            .eq("teacher_id", teacher_id).eq("progression_id", progression_id)
            .eq("semaine", semaine).eq("type", type_document)
            .order("created_at", desc=True).limit(1).execute()
        )
        return reponse.data[0] if reponse.data else None
    except Exception:
        return None


def enregistrer_document_genere(teacher_id, progression_id, semaine, type_document, contenu):
    client = get_client()
    client.table("documents_generes").insert({
        "teacher_id": teacher_id,
        "progression_id": progression_id,
        "semaine": semaine,
        "type": type_document,
        "contenu": contenu,
    }).execute()

# ----------------------------------------------------------------------
# Configuration generale
# ----------------------------------------------------------------------
st.set_page_config(page_title="AcademieIA", page_icon="🔷", layout="centered")

PRIMARY_BLUE = "#00BFAE"
PRIMARY_YELLOW = "#E4002B"
PRIMARY_YELLOW_TEXT = "#FFFFFF"
PRIMARY_YELLOW_LIGHT = "#FDE8EB"

st.markdown(
    f"""
    <style>
    .stApp {{
        background: #FFFFFF;
    }}
    [class*="st-key-fond_accueil"] {{
        background: linear-gradient(135deg, #E0FBF8 0%, {PRIMARY_YELLOW_LIGHT} 100%);
        border-radius: 12px;
        padding: 1.5rem;
    }}
    [class*="st-key-fond_connecte"] {{
        background: #F0997B;
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1rem;
    }}
    .stButton>button {{
        background-color: {PRIMARY_BLUE};
        color: white;
        border-radius: 8px;
        border: none;
    }}
    .badge {{
        display: inline-block;
        background-color: #FDE8EB;
        color: {PRIMARY_BLUE};
        padding: 2px 10px;
        border-radius: 8px;
        font-size: 12px;
    }}
    [class*="st-key-bouton_jaune"] button {{
        background-color: {PRIMARY_YELLOW} !important;
        color: {PRIMARY_YELLOW_TEXT} !important;
    }}
    [class*="st-key-tab_assistant_actif"] button,
    [class*="st-key-tab_niveaux_actif"] button,
    [class*="st-key-tab_historique_actif"] button,
    [class*="st-key-tab_support_actif"] button,
    [class*="st-key-tab_aide_actif"] button {{
        background: transparent !important;
        color: {PRIMARY_YELLOW_TEXT} !important;
        border: none !important;
        border-bottom: 3px solid {PRIMARY_YELLOW} !important;
        border-radius: 0 !important;
        font-weight: 600 !important;
        box-shadow: none !important;
    }}
    [class*="st-key-tab_assistant_inactif"] button,
    [class*="st-key-tab_niveaux_inactif"] button,
    [class*="st-key-tab_historique_inactif"] button,
    [class*="st-key-tab_support_inactif"] button,
    [class*="st-key-tab_aide_inactif"] button {{
        background: transparent !important;
        color: #5f5e5a !important;
        border: none !important;
        border-bottom: 3px solid transparent !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }}
    .stTabs [data-baseweb="tab-list"] {{
        --primary-color: {PRIMARY_YELLOW} !important;
    }}
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"],
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] p,
    .stTabs button[aria-selected="true"] {{
        color: {PRIMARY_YELLOW_TEXT} !important;
    }}
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {{
        border-bottom-color: {PRIMARY_YELLOW} !important;
    }}
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] + div,
    .stTabs div[data-baseweb="tab-list"] > div:last-child {{
        background-color: {PRIMARY_YELLOW} !important;
    }}
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"]:focus-within {{
        border-color: {PRIMARY_YELLOW} !important;
        box-shadow: 0 0 0 1px {PRIMARY_YELLOW} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PROFESSIONS = ["Menuisier aluminium", "Ebeniste", "Autre profession technique"]

# ----------------------------------------------------------------------
# Niveaux et paiement (mobile money)
# ----------------------------------------------------------------------
MONTANT_DEBLOCAGE = "5 000 FCFA"

NIVEAUX_PAR_PROFESSION = {
    "menuiserie_aluminium": [
        "Niveau 1 — Bases de la menuiserie aluminium",
        "Niveau 2 — IA appliquee a la menuiserie aluminium",
        "Niveau 3 — Devis et calculs avances",
        "Niveau 4 — Maitrise et automatisation du metier",
    ],
    "ebenisterie": [
        "Niveau 1 — Bases de l'ebenisterie",
        "Niveau 2 — IA appliquee a l'ebenisterie",
        "Niveau 3 — Finitions et techniques avancees",
        "Niveau 4 — Maitrise et automatisation du metier",
    ],
    "generique": [
        "Niveau 1 — Bases du metier",
        "Niveau 2 — IA appliquee au metier",
        "Niveau 3 — Techniques avancees",
        "Niveau 4 — Maitrise et automatisation du metier",
    ],
}


def obtenir_niveaux(profession):
    """Retourne les 4 niveaux (nom + prix) adaptes au metier saisi a l'inscription."""
    texte = (profession or "").lower()
    if "alu" in texte or "menuisier" in texte:
        cle = "menuiserie_aluminium"
    elif "eben" in texte or "ébén" in texte:
        cle = "ebenisterie"
    else:
        cle = "generique"
    return [{"nom": nom, "prix": MONTANT_DEBLOCAGE} for nom in NIVEAUX_PAR_PROFESSION[cle]]


# ----------------------------------------------------------------------
# Quiz de validation (un par niveau, obligatoire avant de debloquer le niveau suivant)
# ----------------------------------------------------------------------
QUIZ_PAR_NIVEAU = {
    1: [
        {
            "question": "A quoi sert principalement l'assistant IA d'AcademieIA ?",
            "options": ["A remplacer completement votre travail", "A vous aider dans vos taches quotidiennes", "A jouer a des jeux"],
            "reponse_index": 1,
        },
        {
            "question": "Pour obtenir une bonne reponse de l'IA, il vaut mieux :",
            "options": ["Poser une question vague", "Donner du contexte precis sur votre besoin", "Ne rien ecrire"],
            "reponse_index": 1,
        },
        {
            "question": "Si la reponse de l'IA ne vous convient pas, vous pouvez :",
            "options": ["Abandonner", "Reformuler votre question", "Fermer l'application definitivement"],
            "reponse_index": 1,
        },
    ],
    2: [
        {
            "question": "Un bon prompt (question a l'IA) doit surtout etre :",
            "options": ["Court et vague", "Precis et contextualise", "Ecrit en majuscules"],
            "reponse_index": 1,
        },
        {
            "question": "Pour qu'une reponse soit utile a un client, il faut :",
            "options": ["Adapter le langage a la situation", "Copier la reponse brute de l'IA sans relire", "Ignorer le contexte du client"],
            "reponse_index": 0,
        },
        {
            "question": "Essayer plusieurs prompts-modeles differents permet de :",
            "options": ["Perdre du temps", "Decouvrir plusieurs facons d'utiliser l'IA", "Bloquer votre compte"],
            "reponse_index": 1,
        },
    ],
    3: [
        {
            "question": "Etre autonome avec l'IA signifie surtout :",
            "options": ["Ne plus jamais poser de questions", "Savoir formuler ses propres questions sans modele", "Copier les questions des autres"],
            "reponse_index": 1,
        },
        {
            "question": "Si une reponse de l'IA est incomplete, la meilleure reaction est de :",
            "options": ["L'accepter telle quelle", "Preciser ou reformuler la question", "Changer de sujet"],
            "reponse_index": 1,
        },
        {
            "question": "Donner un exemple concret dans votre question aide l'IA a :",
            "options": ["Mieux comprendre votre besoin", "Se tromper davantage", "Repondre plus lentement"],
            "reponse_index": 0,
        },
    ],
    4: [
        {
            "question": "Combiner l'IA avec un tableur (Google Sheets) permet de :",
            "options": ["Automatiser certaines taches repetitives", "Rendre le travail plus complique", "Remplacer completement le tableur"],
            "reponse_index": 0,
        },
        {
            "question": "Un document reutilisable genere avec l'IA doit surtout etre :",
            "options": ["Adapte a votre metier et facilement modifiable", "Fige et jamais modifie", "Ecrit uniquement en anglais"],
            "reponse_index": 0,
        },
        {
            "question": "Le principal avantage de maitriser l'IA dans son metier est de :",
            "options": ["Gagner du temps sur les taches courantes", "Travailler plus lentement", "Ne plus avoir besoin de clients"],
            "reponse_index": 0,
        },
    ],
}


def charger_quiz_reussi(user_id):
    """Charge, pour chaque niveau (1 a 4), si l'utilisateur a deja reussi le quiz de validation."""
    if not SUPABASE_ACTIF or not user_id:
        return {1: False, 2: False, 3: False, 4: False}
    try:
        client = get_client()
        reponse = client.table("users").select(
            "quiz1_reussi, quiz2_reussi, quiz3_reussi, quiz4_reussi"
        ).eq("id", user_id).single().execute()
        donnees = reponse.data or {}
        return {
            1: bool(donnees.get("quiz1_reussi")),
            2: bool(donnees.get("quiz2_reussi")),
            3: bool(donnees.get("quiz3_reussi")),
            4: bool(donnees.get("quiz4_reussi")),
        }
    except Exception:
        return {1: False, 2: False, 3: False, 4: False}


def valider_quiz_reussi(user_id, numero_niveau):
    """Marque le quiz d'un niveau comme reussi pour cet utilisateur."""
    if not SUPABASE_ACTIF or not user_id:
        return
    try:
        client = get_client()
        client.table("users").update({f"quiz{numero_niveau}_reussi": True}).eq("id", user_id).execute()
    except Exception:
        pass


def afficher_quiz_niveau(numero_niveau, user_id):
    """Affiche le quiz de validation d'un niveau (3 questions a choix multiples).
    Retourne True si l'utilisateur vient de le reussir a l'instant (pour declencher un rerun)."""
    questions = QUIZ_PAR_NIVEAU.get(numero_niveau, [])
    if not questions:
        return False
    st.markdown(
        f"""<div style='background:{PRIMARY_YELLOW_LIGHT};border-left:4px solid {PRIMARY_YELLOW};
                    border-radius:8px;padding:10px 14px;margin:8px 0;font-size:13px;'>
            Repondez a ce petit quiz pour valider le Niveau {numero_niveau} et debloquer le niveau suivant.
        </div>""",
        unsafe_allow_html=True,
    )
    reponses_choisies = []
    for index_question, item in enumerate(questions):
        choix = st.radio(
            item["question"],
            options=list(range(len(item["options"]))),
            format_func=lambda i, opts=item["options"]: opts[i],
            key=f"quiz_{numero_niveau}_{index_question}",
            index=None,
        )
        reponses_choisies.append(choix)
    if st.button(f"Valider le quiz du Niveau {numero_niveau}", key=f"btn_valider_quiz_{numero_niveau}", use_container_width=True):
        if any(choix is None for choix in reponses_choisies):
            st.warning("Repondez a toutes les questions avant de valider.")
            return False
        nb_correctes = sum(
            1 for choix, item in zip(reponses_choisies, questions) if choix == item["reponse_index"]
        )
        note_sur_20 = round((nb_correctes / len(questions)) * 20, 1)
        quiz_reussi_maintenant = nb_correctes == len(questions)
        st.markdown(
            f"""<div style='background:var(--surface-2, #F7F7F5);border-radius:8px;padding:10px 14px;margin:8px 0;'>
                <p style='font-size:13px;margin:0;'>Resultat : <strong>{nb_correctes}/{len(questions)}</strong> bonnes reponses</p>
                <p style='font-size:20px;font-weight:600;margin:4px 0 0;color:{PRIMARY_BLUE if quiz_reussi_maintenant else "#B3261E"};'>
                    Note : {note_sur_20}/20
                </p>
            </div>""",
            unsafe_allow_html=True,
        )
        if quiz_reussi_maintenant:
            valider_quiz_reussi(user_id, numero_niveau)
            st.success(f"Felicitations, {note_sur_20}/20 ! Niveau {numero_niveau} valide, vous pouvez debloquer le niveau suivant.")
            return True
        else:
            st.error("Il faut toutes les bonnes reponses pour valider ce quiz. Reessayez !")
    return False


LECONS_PAR_NIVEAU = {
    1: (
        "L'intelligence artificielle est comme un(e) collegue disponible en permanence : elle ne remplace pas "
        "votre savoir-faire, mais elle peut vous faire gagner du temps sur des taches precises (expliquer, "
        "resumer, organiser, redi­ger). Pour bien commencer, essayez simplement de lui poser une question sur "
        "votre metier, comme vous le feriez a un collegue curieux."
    ),
    2: (
        "Plus votre question (ou 'prompt') est precise, meilleure sera la reponse. Une bonne question donne du "
        "contexte : qui vous etes, ce que vous voulez obtenir, et pour qui. Comparez : 'Aide-moi' donne une "
        "reponse vague, alors que 'Redige un message pour expliquer un retard de livraison a un client' donne "
        "une reponse directement utilisable."
    ),
    3: (
        "L'autonomie, c'est savoir formuler ses propres questions sans repartir d'un modele. Si la premiere "
        "reponse ne convient pas, ce n'est pas un echec : reformulez, ajoutez un exemple concret, ou precisez ce "
        "qui manque. Cet aller-retour fait partie normale de l'utilisation de l'IA."
    ),
    4: (
        "La vraie maitrise vient quand vous combinez l'IA avec vos autres outils du quotidien (tableur, "
        "documents, messages) pour automatiser des taches repetitives. L'objectif final n'est pas d'utiliser "
        "l'IA pour l'IA, mais de l'integrer naturellement dans votre facon de travailler."
    ),
}


def afficher_lecon_niveau(numero_niveau):
    """Affiche le court texte pedagogique d'un niveau, avant les exercices pratiques."""
    texte = LECONS_PAR_NIVEAU.get(numero_niveau)
    if not texte:
        return
    st.markdown(
        f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                    border-radius:8px;padding:12px 14px;margin-bottom:12px;font-size:13px;line-height:1.5;'>
            {texte}
        </div>""",
        unsafe_allow_html=True,
    )


OBJECTIFS_PAR_NIVEAU = {
    1: "Decouvrir comment l'IA peut vous aider au quotidien",
    2: "Apprendre a poser de bonnes questions a l'IA",
    3: "Devenir autonome avec vos propres questions",
    4: "Maitriser l'IA en la combinant a vos outils",
}


def afficher_apercu_parcours(niveaux):
    """Affiche un apercu compact des 4 niveaux du parcours, pour montrer d'emblee
    a l'utilisateur ou l'appli va l'emmener. N'affiche que le nom court et l'objectif."""
    st.markdown("<p style='font-size:12px;font-weight:600;margin:0 0 8px;'>Votre parcours de formation</p>", unsafe_allow_html=True)
    cartes = "".join(
        f"""<div style='background:var(--surface-2, #F7F7F5);border-radius:8px;padding:8px 10px;margin-bottom:6px;
                    display:flex;justify-content:space-between;align-items:center;gap:8px;'>
            <span style='font-size:11px;font-weight:600;background:{PRIMARY_BLUE};color:white;border-radius:6px;
                        padding:2px 7px;white-space:nowrap;'>Niveau {numero}</span>
            <span style='font-size:12px;color:var(--text-secondary);flex:1;'>{objectif}</span>
        </div>"""
        for numero, objectif in OBJECTIFS_PAR_NIVEAU.items()
    )
    st.markdown(cartes, unsafe_allow_html=True)
    st.markdown("<hr style='margin:8px 0 4px;'>", unsafe_allow_html=True)


COURS_OUTILS_GOOGLE = [
    {
        "titre": "Google Docs — Traitement de texte",
        "description": "Creer, modifier et mettre en forme des documents (devis, comptes rendus, fiches techniques).",
        "url": "https://support.google.com/a/users/answer/9282664?hl=fr",
    },
    {
        "titre": "Google Sheets — Tableur",
        "description": "Faire des calculs de quantites, des devis chiffres et des tableaux de suivi de chantier.",
        "url": "https://support.google.com/a/users/answer/9282959?hl=fr",
    },
    {
        "titre": "Google Slides — Presentations",
        "description": "Preparer des presentations pour un client ou un cours.",
        "url": "https://support.google.com/a/users/answer/9282488?hl=fr",
    },
    {
        "titre": "Google Drive — Stockage et partage",
        "description": "Stocker ses plans et documents en ligne et les partager facilement.",
        "url": "https://support.google.com/a/users/answer/9310246?hl=fr",
    },
    {
        "titre": "Google Forms — Formulaires",
        "description": "Creer des questionnaires ou des fiches de commande en ligne.",
        "url": "https://support.google.com/a/users/answer/9991170?hl=fr",
    },
    {
        "titre": "Google Meet — Visioconference",
        "description": "Organiser des reunions ou des cours a distance.",
        "url": "https://support.google.com/a/users/answer/9282720?hl=fr",
    },
]

NUMEROS_MOBILE_MONEY = [
    {"operateur": "Wave", "numero": "01 02 93 93 80"},
]
CONTACT_ADMIN_WHATSAPP = "01 02 93 93 80"



if "utilisateurs" not in st.session_state:
    if SUPABASE_ACTIF:
        try:
            st.session_state.utilisateurs = charger_utilisateurs_depuis_supabase()
        except Exception as erreur:
            st.session_state.utilisateurs = pd.DataFrame(columns=["id", "nom", "email", "profession", "role", "inscrit_le"])
            st.session_state.erreur_supabase = str(erreur)
    else:
        st.session_state.utilisateurs = pd.DataFrame([
            {"nom": "Yao Kouassi", "email": "yao.k@example.com", "profession": "Menuisier aluminium", "role": "utilisateur", "inscrit_le": "2026-08-12"},
            {"nom": "Fatou Traore", "email": "fatou.t@example.com", "profession": "Ebeniste", "role": "utilisateur", "inscrit_le": "2026-08-10"},
            {"nom": "Ibrahim Cisse", "email": "ibrahim.c@example.com", "profession": "Menuisier aluminium", "role": "utilisateur", "inscrit_le": "2026-08-09"},
            {"nom": "Adjoua Bamba", "email": "adjoua.b@example.com", "profession": "-", "role": "admin", "inscrit_le": "2026-07-01"},
            {"nom": "Konan Serge", "email": "konan.s@example.com", "profession": "-", "role": "admin", "inscrit_le": "2026-07-03"},
            {"nom": "Aya Kone", "email": "super@example.com", "profession": "-", "role": "super_admin", "inscrit_le": "2026-06-01"},
        ])

if "utilisateur_connecte" not in st.session_state:
    st.session_state.utilisateur_connecte = None

if "ecran" not in st.session_state:
    st.session_state.ecran = "accueil"

if "onglet_auth_par_defaut" not in st.session_state:
    st.session_state.onglet_auth_par_defaut = "Connexion"

if "niveau2_prompt_choisi" not in st.session_state:
    st.session_state.niveau2_prompt_choisi = None

if "niveau4_prompt_choisi" not in st.session_state:
    st.session_state.niveau4_prompt_choisi = None

def ecran_accueil():
    col_gauche, col_centre, col_droite = st.columns([1, 2, 1])
    with col_centre, st.container(key="fond_accueil"):
        st.markdown(
            f"""
            <div style='text-align:center; padding: 2rem 0 1rem;'>
                <div style='width:64px;height:64px;border-radius:16px;background:{PRIMARY_YELLOW_LIGHT};
                            display:flex;align-items:center;justify-content:center;margin:0 auto 1.25rem;font-size:28px;'>
                    🔷
                </div>
                <p style='font-size:20px;font-weight:500;margin:0 0 6px;'>AcademieIA</p>
                <p style='font-size:13px;color:var(--text-secondary);margin:0 0 1.5rem;'>
                    L'assistant IA des professionnels par metier
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Se connecter", key="btn_accueil_connexion", use_container_width=True):
            st.session_state.onglet_auth_par_defaut = "Connexion"
            st.session_state.ecran = "auth"
            st.rerun()

        with st.container(key="bouton_jaune_inscription_accueil"):
            if st.button("Creer un compte", key="btn_accueil_inscription", use_container_width=True):
                st.session_state.onglet_auth_par_defaut = "Inscription"
                st.session_state.ecran = "auth"
                st.rerun()

        st.markdown(
            "<p style='font-size:11px;color:var(--text-muted);text-align:center;margin-top:12px;'>"
            "Les comptes admin sont crees par un super administrateur."
            "</p>",
            unsafe_allow_html=True,
        )
        if not SUPABASE_ACTIF:
            st.caption("Mode demo : configurez SUPABASE_URL et SUPABASE_ANON_KEY dans les secrets pour brancher la vraie base.")


def ecran_authentification():
    col_gauche, col_centre, col_droite = st.columns([1, 2, 1])
    with col_centre:
        if st.button("← Retour", key="btn_retour_accueil"):
            st.session_state.ecran = "accueil"
            st.rerun()

        st.markdown(
            f"""<div style='text-align:center; margin-bottom: 0.5rem;'>
                <div style='width:48px;height:48px;border-radius:12px;background:{PRIMARY_YELLOW_LIGHT};
                            display:flex;align-items:center;justify-content:center;margin:0 auto;font-size:22px;'>
                    🔷
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        onglet_connexion, onglet_inscription = st.tabs(["Connexion", "Inscription"])

        with onglet_connexion:
            email = st.text_input("Email", key="login_email", placeholder="nom@etablissement.ci")
            mot_de_passe = st.text_input("Mot de passe", key="login_mdp", type="password")
            if st.button("Se connecter", key="btn_login", use_container_width=True):
                if SUPABASE_ACTIF:
                    try:
                        client = get_client()
                        hash_saisi = hasher_mot_de_passe(mot_de_passe)
                        resultat = client.rpc(
                            "verifier_login",
                            {"p_identifiant": email, "p_hash": hash_saisi},
                        ).execute()
                        if resultat.data:
                            ligne = resultat.data[0]
                            st.session_state.utilisateur_connecte = {
                                "id": ligne.get("id"),
                                "nom": ligne.get("nom") or ligne.get("username"),
                                "role": ligne.get("role", "utilisateur"),
                                "profession": ligne.get("profession"),
                            }
                            st.rerun()
                        else:
                            st.error("Email ou mot de passe incorrect.")
                    except Exception as erreur:
                        st.error(f"Erreur de connexion a la base : {erreur}")
                else:
                    correspondance = st.session_state.utilisateurs[
                        st.session_state.utilisateurs["email"] == email
                    ]
                    if not correspondance.empty:
                        ligne = correspondance.iloc[0]
                        st.session_state.utilisateur_connecte = {
                            "id": ligne.get("id") if "id" in ligne else None,
                            "nom": ligne["nom"],
                            "role": ligne["role"],
                            "profession": ligne["profession"],
                        }
                        st.rerun()
                    else:
                        st.error("Email introuvable. Essayez yao.k@example.com pour la demo.")

        with onglet_inscription:
            nom = st.text_input("Nom complet", key="signup_nom", placeholder="Kouassi Yao")
            email_inscription = st.text_input("Email", key="signup_email", placeholder="nom@etablissement.ci")
            role_inscription = st.selectbox("Vous etes :", ["Un(e) professionnel(le)", "Un(e) enseignant(e)"], key="signup_role")
            est_enseignant = role_inscription == "Un(e) enseignant(e)"
            profession = st.text_input(
                "Profession" if not est_enseignant else "Matiere enseignee (optionnel ici, a preciser ensuite)",
                key="signup_profession",
                placeholder="Ex : menuisier aluminium, plombier, electricien..." if not est_enseignant else "Ex : Menuiserie aluminium",
            )
            mdp_inscription = st.text_input("Mot de passe", key="signup_mdp", type="password")

            st.caption("Les comptes admin sont crees uniquement par un super administrateur.")

            with st.container(key="bouton_jaune_signup"):
                if st.button("Creer mon compte", key="btn_signup", use_container_width=True):
                    if not nom or not email_inscription or not mdp_inscription or (not est_enseignant and not profession):
                        st.error("Merci de remplir tous les champs.")
                    elif SUPABASE_ACTIF:
                        try:
                            client = get_client()
                            existe_deja = (
                                client.table("users")
                                .select("id")
                                .eq("email", email_inscription)
                                .execute()
                            )
                            if existe_deja.data:
                                st.error("Un compte existe deja avec cet email.")
                            else:
                                client.table("users").insert({
                                    "username": email_inscription.split("@")[0],
                                    "nom": nom,
                                    "email": email_inscription,
                                    "profession": profession,
                                    "role": "enseignant" if est_enseignant else "utilisateur",
                                    "password_hash": hasher_mot_de_passe(mdp_inscription),
                                    "created_at": datetime.now().isoformat(),
                                }, returning="minimal").execute()
                                st.success("Compte cree. Vous pouvez vous connecter.")
                        except Exception as erreur:
                            st.error(f"Impossible de creer le compte : {erreur}")
                    else:
                        nouvelle_ligne = {
                            "nom": nom,
                            "email": email_inscription,
                            "profession": profession,
                            "role": "enseignant" if est_enseignant else "utilisateur",
                            "inscrit_le": str(date.today()),
                        }
                        st.session_state.utilisateurs = pd.concat(
                            [st.session_state.utilisateurs, pd.DataFrame([nouvelle_ligne])],
                            ignore_index=True,
                        )
                        st.success("Compte cree. Vous pouvez vous connecter.")

        st.markdown("<hr style='margin:16px 0;'>", unsafe_allow_html=True)
        with st.expander("🧭 Besoin d'aide pour vous inscrire ou vous connecter ?"):
            questions_frequentes_auth = [
                "Comment creer un compte ?",
                "J'ai oublie mon mot de passe, que faire ?",
                "Pourquoi mon email n'est pas reconnu ?",
                "Que faire apres avoir cree mon compte ?",
            ]
            question_aide_auth_a_poser = None
            col_qa1, col_qa2 = st.columns(2)
            for index_qa, question_rapide_auth in enumerate(questions_frequentes_auth):
                colonne_auth = col_qa1 if index_qa % 2 == 0 else col_qa2
                with colonne_auth:
                    if st.button(question_rapide_auth, key=f"aide_auth_rapide_{index_qa}", use_container_width=True):
                        question_aide_auth_a_poser = question_rapide_auth
            st.text_area("Ou posez votre propre question", key="question_aide_auth", placeholder="Ex : comment savoir si mon compte est bien cree ?")
            if st.button("Demander de l'aide", key="btn_envoyer_aide_auth", use_container_width=True):
                question_aide_auth_a_poser = st.session_state.get("question_aide_auth", "").strip()
            if question_aide_auth_a_poser is not None:
                if not question_aide_auth_a_poser:
                    st.warning("Ecris ta question avant d'envoyer.")
                elif not GROQ_ACTIF:
                    st.info("Chat d'aide pas encore configure : ajoutez GROQ_API_KEY dans les secrets.")
                else:
                    with st.spinner("Recherche de la reponse..."):
                        try:
                            reponse_aide_auth = repondre_aide_appli(question_aide_auth_a_poser)
                            st.markdown(
                                f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                                            border-radius:8px;padding:14px 16px;margin-top:8px;'>{reponse_aide_auth}</div>""",
                                unsafe_allow_html=True,
                            )
                        except Exception as erreur:
                            st.error(f"Le chat d'aide n'a pas pu repondre : {erreur}")


def afficher_suppression_compte(comptes, cle_widget):
    """Selecteur + bouton de suppression definitive d'un compte, avec confirmation obligatoire.
    'comptes' est un DataFrame avec au moins les colonnes id, nom, email."""
    if not SUPABASE_ACTIF:
        st.info("Mode demo : la suppression de compte necessite Supabase configure.")
        return

    if st.session_state.get(f"dernier_compte_supprime_{cle_widget}"):
        st.success(st.session_state[f"dernier_compte_supprime_{cle_widget}"])
        st.session_state[f"dernier_compte_supprime_{cle_widget}"] = None

    if comptes.empty or "id" not in comptes.columns:
        st.caption("Aucun compte disponible.")
        return

    options = {
        f"{ligne.get('nom') or '-'} ({ligne.get('email') or '-'})": ligne["id"]
        for _, ligne in comptes.iterrows()
    }
    choix_libelle = st.selectbox("Compte a supprimer", options.keys(), key=f"choix_suppr_{cle_widget}")
    confirmation = st.checkbox(
        "Je confirme vouloir supprimer definitivement ce compte (irreversible)",
        key=f"confirm_suppr_{cle_widget}",
    )
    if st.button("Supprimer definitivement ce compte", key=f"btn_suppr_{cle_widget}", disabled=not confirmation):
        try:
            supprimer_compte(options[choix_libelle])
            st.session_state.pop("utilisateurs", None)
            st.session_state[f"dernier_compte_supprime_{cle_widget}"] = f"Compte {choix_libelle} supprime."
            st.rerun()
        except Exception as erreur:
            st.error(f"Impossible de supprimer ce compte : {erreur}")


def carte_metrique(titre, valeur, couleur=None):
    """Carte de statistique stylee (remplace st.metric pour garder les couleurs de la marque)."""
    couleur = couleur or PRIMARY_BLUE
    st.markdown(
        f"""<div style='background:var(--surface-1, #f1efe8);border-radius:8px;padding:12px;
                    border-left:3px solid {couleur};margin-bottom:8px;'>
            <p style='font-size:13px;color:var(--text-secondary, #5f5e5a);margin:0 0 4px;'>{titre}</p>
            <p style='font-size:24px;font-weight:500;margin:0;color:{couleur};'>{valeur}</p>
        </div>""",
        unsafe_allow_html=True,
    )


def afficher_demandes_paiement(utilisateurs):
    """Affiche les demandes de paiement en attente avec boutons Approuver / Rejeter,
    et un historique separe des demandes deja traitees (approuvees/rejetees).
    Reutilisable dans le dashboard admin et super_admin."""
    if not SUPABASE_ACTIF:
        st.info("Mode demo : la gestion des demandes de paiement necessite Supabase configure.")
        return

    if st.session_state.get("dernier_code_genere"):
        st.success(st.session_state.dernier_code_genere)
        if st.button("OK, j'ai note le code", key="btn_effacer_code_genere"):
            st.session_state.dernier_code_genere = None
            st.rerun()

    demandes = charger_demandes_paiement(statut="en_attente")

    if not demandes.empty:
        demandes = demandes.sort_values("created_at", ascending=False).drop_duplicates(
            subset="user_id", keep="first"
        )

    if "id" in utilisateurs.columns and not demandes.empty:
        demandes = demandes.merge(
            utilisateurs[["id", "nom", "email"]],
            left_on="user_id", right_on="id", how="left", suffixes=("", "_utilisateur"),
        )

    if demandes.empty:
        st.caption("Aucune demande de paiement en attente.")
    else:
        for _, demande in demandes.iterrows():
            nom_client = demande.get("nom") or demande.get("user_id")
            email_client = demande.get("email") or "-"
            st.markdown(
                f"""<div style='background:var(--surface-2, #F7F7F5);border:0.5px solid var(--border, #E5E4E1);
                            border-radius:8px;padding:10px 12px;margin-bottom:6px;'>
                    <p style='font-size:14px;font-weight:600;margin:0;'>{nom_client}</p>
                    <p style='font-size:12px;color:var(--text-secondary, #5f5e5a);margin:2px 0 0;'>{email_client}</p>
                    <p style='font-size:13px;margin:6px 0 0;'>Niveau demande : <strong>{demande.get("niveau")}</strong></p>
                    <p style='font-size:12px;color:var(--text-secondary, #5f5e5a);margin:2px 0 0;'>
                        Reference : {demande.get("reference") or "-"} · {demande.get("created_at", "")[:16]}
                    </p>
                </div>""",
                unsafe_allow_html=True,
            )
            col_approuver, col_rejeter = st.columns(2)
            with col_approuver:
                with st.container(key=f"bouton_jaune_approuver_{demande['id']}"):
                    if st.button("Approuver et generer un code", key=f"btn_approuver_{demande['id']}", use_container_width=True):
                        try:
                            code = generer_code_acces()
                            approuver_demande_paiement(demande["id"], demande["niveau"], code, demande["user_id"])
                            st.session_state.dernier_code_genere = (
                                f"Code genere pour {nom_client} : {code} — a transmettre par WhatsApp."
                            )
                            st.rerun()
                        except Exception as erreur:
                            st.error(f"Impossible d'approuver la demande : {erreur}")
            with col_rejeter:
                if st.button("Rejeter", key=f"btn_rejeter_{demande['id']}", use_container_width=True):
                    try:
                        rejeter_demande_paiement(demande["id"], demande["user_id"])
                        st.rerun()
                    except Exception as erreur:
                        st.error(f"Impossible de rejeter la demande : {erreur}")

    with st.expander("Historique des demandes traitees"):
        historique = charger_demandes_paiement()
        if "id" in utilisateurs.columns and not historique.empty:
            historique = historique.merge(
                utilisateurs[["id", "nom", "email"]],
                left_on="user_id", right_on="id", how="left", suffixes=("", "_utilisateur"),
            )
        historique = (
            historique[~historique["statut"].isin(["en_attente", "obsolete"])]
            if not historique.empty else historique
        )

        if historique.empty:
            st.caption("Aucune demande traitee pour le moment.")
        else:
            for _, demande in historique.sort_values("created_at", ascending=False).iterrows():
                nom_client = demande.get("nom") or demande.get("user_id")
                statut = demande.get("statut")
                couleur_statut = PRIMARY_BLUE if statut == "approuvee" else "#B3261E"
                libelle_statut = "Approuvee" if statut == "approuvee" else "Rejetee"
                code_ligne = (
                    f"<p style='font-size:12px;margin:4px 0 0;'>Code : <strong>{demande.get('code_genere')}</strong></p>"
                    if statut == "approuvee" and demande.get("code_genere") else ""
                )
                st.markdown(
                    f"""<div style='background:var(--surface-2, #F7F7F5);border:0.5px solid var(--border, #E5E4E1);
                                border-radius:8px;padding:10px 12px;margin-bottom:6px;'>
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <p style='font-size:14px;font-weight:600;margin:0;'>{nom_client}</p>
                            <span style='font-size:11px;background:{couleur_statut};color:white;padding:2px 8px;border-radius:8px;'>{libelle_statut}</span>
                        </div>
                        <p style='font-size:13px;margin:6px 0 0;'>Niveau : {demande.get("niveau")}</p>
                        {code_ligne}
                    </div>""",
                    unsafe_allow_html=True,
                )



def ecran_admin():
    with st.container(key="fond_connecte"):
        if st.session_state.get("erreur_supabase"):
            st.error(f"Erreur de connexion a Supabase : {st.session_state.erreur_supabase}")

        utilisateurs = st.session_state.utilisateurs
        seulement_utilisateurs = utilisateurs[utilisateurs["role"] == "utilisateur"]

        carte_metrique("Utilisateurs", len(seulement_utilisateurs), PRIMARY_YELLOW)

        st.markdown("**Statistiques d'usage**")
        stats = charger_statistiques_globales()
        col_stat1, col_stat2 = st.columns(2)
        with col_stat1:
            carte_metrique("Questions posees (total)", stats["total_questions"], PRIMARY_BLUE)
            carte_metrique("Niveau 1 termine", stats["niveau1_complete"], PRIMARY_BLUE)
        with col_stat2:
            carte_metrique("Niveau 2 termine", stats["niveau2_complete"], PRIMARY_BLUE)
            carte_metrique("Niveau 3 termine", stats["niveau3_complete"], PRIMARY_BLUE)

        st.markdown("**Utilisateurs**")
        recherche = st.text_input("Rechercher un utilisateur", key="recherche_admin", label_visibility="collapsed", placeholder="Rechercher un utilisateur")
        resultat = seulement_utilisateurs[seulement_utilisateurs["nom"].str.contains(recherche, case=False)] if recherche else seulement_utilisateurs
        st.dataframe(resultat[["nom", "profession", "inscrit_le"]], use_container_width=True, hide_index=True)

        with st.expander("Supprimer un compte utilisateur"):
            afficher_suppression_compte(seulement_utilisateurs, "admin_utilisateur")

        st.markdown("**Demandes de paiement en attente**")
        afficher_demandes_paiement(utilisateurs)

        st.markdown("**Messages support**")
        conversations = charger_conversations_admin()
        if not conversations:
            st.caption("Aucun message pour l'instant.")
        else:
            noms_par_id = dict(zip(seulement_utilisateurs["id"], seulement_utilisateurs["nom"]))
            cle_conversation_choisie = st.selectbox(
                "Choisir une conversation",
                options=[c["user_id"] for c in conversations],
                format_func=lambda uid: noms_par_id.get(uid, f"Utilisateur #{uid}"),
                key="conversation_admin_choisie",
            )
            if cle_conversation_choisie is not None:
                messages_thread = charger_messages_utilisateur(cle_conversation_choisie)
                for message in messages_thread:
                    est_utilisateur = message.get("auteur") == "utilisateur"
                    couleur_fond = "var(--surface-2, #F7F7F5)" if est_utilisateur else "#FDE8EB"
                    libelle_auteur = noms_par_id.get(cle_conversation_choisie, "Utilisateur") if est_utilisateur else (message.get("auteur") or "Admin")
                    st.markdown(
                        f"""<div style='background:{couleur_fond};border-radius:8px;padding:10px 12px;margin-bottom:8px;'>
                            <p style='font-size:11px;font-weight:600;margin:0;color:var(--text-secondary);'>{libelle_auteur}</p>
                            <p style='font-size:14px;margin:4px 0 0;'>{message.get("contenu")}</p>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                st.text_area("Reponse", key="reponse_admin_support", placeholder="Ecrire une reponse...")
                if st.button("Envoyer la reponse", key="btn_envoyer_reponse_admin", use_container_width=True):
                    contenu_reponse = st.session_state.get("reponse_admin_support", "").strip()
                    if not contenu_reponse:
                        st.warning("Ecris une reponse avant d'envoyer.")
                    else:
                        nom_admin = st.session_state.utilisateur_connecte.get("nom") or "Admin"
                        envoyer_message_support(cle_conversation_choisie, nom_admin, contenu_reponse)
                        st.success("Reponse envoyee.")
                        st.rerun()

        st.caption("Un admin ne peut ni creer d'autres comptes admin ni voir le tableau de bord des admins.")


def ecran_super_admin():
    with st.container(key="fond_connecte"):
        if st.session_state.get("erreur_supabase"):
            st.error(f"Erreur de connexion a Supabase : {st.session_state.erreur_supabase}")

        utilisateurs = st.session_state.utilisateurs
        seulement_utilisateurs = utilisateurs[utilisateurs["role"] == "utilisateur"]
        seulement_admins = utilisateurs[utilisateurs["role"] == "admin"]

        col1, col2 = st.columns(2)
        with col1:
            carte_metrique("Utilisateurs", len(seulement_utilisateurs), PRIMARY_YELLOW)
        with col2:
            carte_metrique("Admins", len(seulement_admins), PRIMARY_YELLOW)

        st.markdown("**Statistiques d'usage**")
        stats = charger_statistiques_globales()
        col_stat1, col_stat2 = st.columns(2)
        with col_stat1:
            carte_metrique("Questions posees (total)", stats["total_questions"], PRIMARY_BLUE)
            carte_metrique("Niveau 1 termine", stats["niveau1_complete"], PRIMARY_BLUE)
        with col_stat2:
            carte_metrique("Niveau 2 termine", stats["niveau2_complete"], PRIMARY_BLUE)
            carte_metrique("Niveau 3 termine", stats["niveau3_complete"], PRIMARY_BLUE)
        carte_metrique("Niveau 4 termine (certificat)", stats["niveau4_complete"], PRIMARY_YELLOW)

        st.markdown("**Comptes admin**")
        st.dataframe(seulement_admins[["nom", "email"]], use_container_width=True, hide_index=True)

        with st.expander("Supprimer un compte (utilisateur ou admin)"):
            comptes_supprimables = pd.concat([seulement_utilisateurs, seulement_admins], ignore_index=True)
            afficher_suppression_compte(comptes_supprimables, "super_admin_tous")

        st.markdown("**Demandes de paiement en attente**")
        afficher_demandes_paiement(utilisateurs)

        with st.expander("Creer un compte admin"):
            nom_admin = st.text_input("Nom complet", key="nom_nouvel_admin")
            email_admin = st.text_input("Email", key="email_nouvel_admin")
            mdp_admin = st.text_input("Mot de passe attribue", key="mdp_nouvel_admin", type="password")
            with st.container(key="bouton_jaune_creer_admin"):
                if st.button("Creer l'admin", key="btn_creer_admin"):
                    if not nom_admin or not email_admin or not mdp_admin:
                        st.error("Merci de remplir tous les champs.")
                    elif SUPABASE_ACTIF:
                        try:
                            client = get_client()
                            existe_deja = client.table("users").select("id").eq("email", email_admin).execute()
                            if existe_deja.data:
                                st.error("Un compte existe deja avec cet email.")
                            else:
                                client.table("users").insert({
                                    "username": email_admin.split("@")[0],
                                    "nom": nom_admin,
                                    "email": email_admin,
                                    "profession": "-",
                                    "role": "admin",
                                    "password_hash": hasher_mot_de_passe(mdp_admin),
                                    "created_at": datetime.now().isoformat(),
                                }, returning="minimal").execute()
                                st.success(f"Compte admin cree pour {nom_admin}.")
                                st.session_state.pop("utilisateurs", None)
                                st.rerun()
                        except Exception as erreur:
                            st.error(f"Impossible de creer l'admin : {erreur}")
                    else:
                        nouvelle_ligne = {
                            "nom": nom_admin,
                            "email": email_admin,
                            "profession": "-",
                            "role": "admin",
                            "inscrit_le": str(date.today()),
                        }
                        st.session_state.utilisateurs = pd.concat(
                            [st.session_state.utilisateurs, pd.DataFrame([nouvelle_ligne])],
                            ignore_index=True,
                        )
                        st.success(f"Compte admin cree pour {nom_admin}.")
                        st.rerun()

        st.markdown("**Tous les utilisateurs**")
        recherche = st.text_input("Rechercher un utilisateur", key="recherche_super", label_visibility="collapsed", placeholder="Rechercher un utilisateur")
        resultat = utilisateurs[utilisateurs["nom"].str.contains(recherche, case=False)] if recherche else utilisateurs
        st.dataframe(resultat[["nom", "profession", "role", "inscrit_le"]], use_container_width=True, hide_index=True)


def ecran_utilisateur():
    with st.container(key="fond_connecte"):
        utilisateur = st.session_state.utilisateur_connecte
        niveaux_debloques = charger_niveaux_utilisateur(utilisateur.get("id"))

        st.markdown(
            f"""<div style='background:#FDE8EB;border-radius:12px;padding:12px 14px;margin-bottom:1rem;'>
                <p style='font-size:13px;margin:0;'>Bienvenue, <strong>{utilisateur.get('nom')}</strong></p>
                <p style='font-size:12px;margin:4px 0 0;color:var(--text-secondary);'>{utilisateur.get('profession') or '-'}</p>
            </div>""",
            unsafe_allow_html=True,
        )

        if not niveaux_debloques:
            afficher_apercu_parcours(obtenir_niveaux(utilisateur.get("profession")))

        if "onglet_utilisateur_actif" not in st.session_state:
            st.session_state.onglet_utilisateur_actif = "assistant"

        niveaux = obtenir_niveaux(utilisateur.get("profession"))

        col_tab1, col_tab2, col_tab3, col_tab4, col_tab5 = st.columns(5)
        with col_tab1:
            cle = "tab_assistant_actif" if st.session_state.onglet_utilisateur_actif == "assistant" else "tab_assistant_inactif"
            with st.container(key=cle):
                if st.button("Assistant IA", key="btn_onglet_assistant", use_container_width=True):
                    st.session_state.onglet_utilisateur_actif = "assistant"
                    st.rerun()
        with col_tab2:
            cle = "tab_niveaux_actif" if st.session_state.onglet_utilisateur_actif == "niveaux" else "tab_niveaux_inactif"
            with st.container(key=cle):
                if st.button("Mes niveaux", key="btn_onglet_niveaux", use_container_width=True):
                    st.session_state.onglet_utilisateur_actif = "niveaux"
                    st.rerun()
        with col_tab3:
            cle = "tab_historique_actif" if st.session_state.onglet_utilisateur_actif == "historique" else "tab_historique_inactif"
            with st.container(key=cle):
                if st.button("Historique", key="btn_onglet_historique", use_container_width=True):
                    st.session_state.onglet_utilisateur_actif = "historique"
                    st.rerun()
        with col_tab4:
            cle = "tab_support_actif" if st.session_state.onglet_utilisateur_actif == "support" else "tab_support_inactif"
            with st.container(key=cle):
                if st.button("Support", key="btn_onglet_support", use_container_width=True):
                    st.session_state.onglet_utilisateur_actif = "support"
                    st.rerun()
        with col_tab5:
            cle = "tab_aide_actif" if st.session_state.onglet_utilisateur_actif == "aide" else "tab_aide_inactif"
            with st.container(key=cle):
                if st.button("Aide", key="btn_onglet_aide", use_container_width=True):
                    st.session_state.onglet_utilisateur_actif = "aide"
                    st.rerun()

        st.markdown("<hr style='margin-top:0;'>", unsafe_allow_html=True)


        if st.session_state.onglet_utilisateur_actif == "aide":
            st.markdown("##### 🧭 Aide — comment utiliser AcademieIA")
            st.caption("Ce chat repond a vos questions sur la navigation dans l'appli (pas sur votre metier).")
            questions_frequentes = [
                "Comment debloquer le Niveau 2 ?",
                "Comment fonctionne le quiz ?",
                "Ou voir mes anciennes questions ?",
                "Comment contacter un administrateur ?",
            ]
            question_aide_a_poser = None
            col_q1, col_q2 = st.columns(2)
            for index_q, question_rapide in enumerate(questions_frequentes):
                colonne = col_q1 if index_q % 2 == 0 else col_q2
                with colonne:
                    if st.button(question_rapide, key=f"aide_rapide_{index_q}", use_container_width=True):
                        question_aide_a_poser = question_rapide
            st.text_area("Ou posez votre propre question", key="question_aide", placeholder="Ex : comment obtenir mon certificat ?")
            if st.button("Demander de l'aide", key="btn_envoyer_aide", use_container_width=True):
                question_aide_a_poser = st.session_state.get("question_aide", "").strip()
            if question_aide_a_poser is not None:
                if not question_aide_a_poser:
                    st.warning("Ecris ta question avant d'envoyer.")
                elif not GROQ_ACTIF:
                    st.info("Chat d'aide pas encore configure : ajoutez GROQ_API_KEY dans les secrets.")
                else:
                    with st.spinner("Recherche de la reponse..."):
                        try:
                            reponse_aide = repondre_aide_appli(question_aide_a_poser)
                            st.markdown(
                                f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                                            border-radius:8px;padding:14px 16px;margin-top:8px;'>{reponse_aide}</div>""",
                                unsafe_allow_html=True,
                            )
                        except Exception as erreur:
                            st.error(f"Le chat d'aide n'a pas pu repondre : {erreur}")

        elif st.session_state.onglet_utilisateur_actif == "historique":
            st.markdown("##### 🕘 Historique de vos questions")
            historique = charger_historique_utilisateur(utilisateur.get("id"))
            if not historique:
                st.caption("Aucune question posee pour l'instant. Rendez-vous dans l'onglet Assistant IA.")
            else:
                for echange in historique:
                    st.markdown(
                        f"""<div style='background:var(--surface-2, #F7F7F5);border:0.5px solid var(--border, #E5E4E1);
                                    border-radius:8px;padding:10px 12px;margin-bottom:10px;'>
                            <p style='font-size:13px;font-weight:600;margin:0;'>{echange.get("question")}</p>
                            <p style='font-size:11px;color:var(--text-secondary);margin:4px 0 6px;'>{echange.get("cree_le", "")[:16]}</p>
                            <p style='font-size:13px;margin:0;color:var(--text-secondary);'>{echange.get("reponse")}</p>
                        </div>""",
                        unsafe_allow_html=True,
                    )

        elif st.session_state.onglet_utilisateur_actif == "support":
            st.markdown("##### 💬 Support — echangez avec un admin")
            messages_utilisateur = charger_messages_utilisateur(utilisateur.get("id"))
            if not messages_utilisateur:
                st.caption("Aucun message pour l'instant. Ecrivez votre premiere question ci-dessous.")
            for message in messages_utilisateur:
                est_utilisateur = message.get("auteur") == "utilisateur"
                couleur_fond = "#FDE8EB" if est_utilisateur else "var(--surface-2, #F7F7F5)"
                libelle_auteur = "Vous" if est_utilisateur else (message.get("auteur") or "Admin")
                st.markdown(
                    f"""<div style='background:{couleur_fond};border-radius:8px;padding:10px 12px;margin-bottom:8px;'>
                        <p style='font-size:11px;font-weight:600;margin:0;color:var(--text-secondary);'>{libelle_auteur}</p>
                        <p style='font-size:14px;margin:4px 0 0;'>{message.get("contenu")}</p>
                    </div>""",
                    unsafe_allow_html=True,
                )
            st.text_area("Votre message", key="nouveau_message_support", placeholder="Ecrivez votre question ou votre probleme ici...")
            if st.button("Envoyer au support", key="btn_envoyer_support", use_container_width=True):
                contenu_message = st.session_state.get("nouveau_message_support", "").strip()
                if not contenu_message:
                    st.warning("Ecris ton message avant d'envoyer.")
                else:
                    envoyer_message_support(utilisateur.get("id"), "utilisateur", contenu_message)
                    st.success("Message envoye ! Un admin vous repondra prochainement.")
                    st.rerun()

        elif st.session_state.onglet_utilisateur_actif == "assistant":
            noms_debloques = [n["nom"] for n in niveaux if n["nom"] in niveaux_debloques]
            niveaux_texte = " + ".join(noms_debloques) if noms_debloques else "Aucun niveau debloque"

            quota_max = obtenir_quota_max(noms_debloques)
            questions_utilisees_aujourdhui = charger_quota_utilisateur(utilisateur.get("id"))
            quota_texte = (
                "Questions illimitees"
                if quota_max is None
                else f"{questions_utilisees_aujourdhui}/{quota_max} questions utilisees aujourd'hui"
            )
            st.markdown(
                f"""<div style='background:var(--surface-2);border-radius:8px;padding:8px 12px;margin-bottom:12px;
                            font-size:12px;color:var(--text-secondary);'>
                    Niveau actif : <strong style='color:{PRIMARY_BLUE};'>{niveaux_texte}</strong><br>
                    {quota_texte}
                </div>""",
                unsafe_allow_html=True,
            )

            progression_niveau1 = charger_progression_niveau1(utilisateur.get("id"))
            profession_utilisateur = utilisateur.get("profession") or "votre metier"
            question_a_envoyer = None

            if not progression_niveau1["niveau1_complete"]:
                st.markdown("##### 🎓 Niveau 1 — Prise en main")
                afficher_lecon_niveau(1)
                st.markdown(
                    f"Vous etes **{profession_utilisateur}**. Decouvrons ensemble comment "
                    f"l'IA peut vous aider, en 3 essais simples : cliquez sur un exemple ci-dessous."
                )
                prompts_exemple_niveau1 = [
                    f"Explique-moi en 3 points ce que tu peux faire pour un(e) {profession_utilisateur}",
                    f"Donne-moi un exemple simple de tache que tu peux faire pour un(e) {profession_utilisateur}",
                    f"Aide-moi a resoudre un probleme courant que rencontre un(e) {profession_utilisateur}",
                ]
                for index_prompt, prompt_exemple in enumerate(prompts_exemple_niveau1):
                    if st.button(prompt_exemple, key=f"prompt_exemple_niveau1_{index_prompt}", use_container_width=True):
                        question_a_envoyer = prompt_exemple
                st.markdown(
                    "*Astuce : vous pouvez aussi ecrire votre propre question ci-dessous "
                    "pour terminer le Niveau 1.*"
                )
                st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)

            niveau2_debloque = any(nom.startswith("Niveau 2") for nom in noms_debloques)
            progression_niveau2 = (
                charger_progression_niveau2(utilisateur.get("id"))
                if progression_niveau1["niveau1_complete"] and niveau2_debloque
                else {"prompts_utilises_niveau2": [], "niveau2_complete": True}
            )

            if progression_niveau1["niveau1_complete"] and niveau2_debloque and not progression_niveau2["niveau2_complete"]:
                st.markdown("##### 🚀 Niveau 2 — Usage guide")
                afficher_lecon_niveau(2)
                st.markdown(
                    "Voici des modeles de questions liees a votre metier. Cliquez-en un pour le "
                    "pre-remplir ci-dessous, modifiez-le si besoin, puis envoyez-le. "
                    "*Essayez-en au moins 3 differents pour terminer ce niveau.*"
                )
                prompts_modeles_niveau2 = [
                    f"Aide-moi a rediger un message professionnel pour expliquer a un client ce que fait un(e) {profession_utilisateur}",
                    f"Resume-moi une information complexe liee a mon metier de {profession_utilisateur}, en langage simple pour un client",
                    f"Aide-moi a preparer une liste de questions a poser a un client avant de commencer un travail de {profession_utilisateur}",
                    f"Donne-moi un plan simple pour organiser ma journee de travail en tant que {profession_utilisateur}",
                    f"Aide-moi a rediger une reponse polie a un client mecontent, dans le contexte de mon metier de {profession_utilisateur}",
                    f"Explique-moi comment un(e) {profession_utilisateur} peut utiliser l'IA pour gagner du temps sur les taches administratives",
                ]
                for index_modele, prompt_modele in enumerate(prompts_modeles_niveau2):
                    deja_utilise = str(index_modele) in progression_niveau2["prompts_utilises_niveau2"]
                    libelle = f"✓ {prompt_modele}" if deja_utilise else prompt_modele
                    if st.button(libelle, key=f"prompt_modele_niveau2_{index_modele}", use_container_width=True):
                        st.session_state.question_assistant = prompt_modele
                        st.session_state.niveau2_prompt_choisi = index_modele
                        question_a_envoyer = prompt_modele
                st.caption(f"Prompts essayes : {len(set(progression_niveau2['prompts_utilises_niveau2']))}/3")
                st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)

            niveau3_debloque = any(nom.startswith("Niveau 3") for nom in noms_debloques)
            niveau2_reellement_termine = not niveau2_debloque or progression_niveau2["niveau2_complete"]
            progression_niveau3 = (
                charger_progression_niveau3(utilisateur.get("id"))
                if progression_niveau1["niveau1_complete"] and niveau2_reellement_termine and niveau3_debloque
                else {"messages_envoyes_niveau3": 0, "niveau3_complete": True}
            )

            if (
                progression_niveau1["niveau1_complete"]
                and niveau2_reellement_termine
                and niveau3_debloque
                and not progression_niveau3["niveau3_complete"]
            ):
                st.markdown("##### 🧭 Niveau 3 — Autonomie")
                afficher_lecon_niveau(3)
                st.markdown(
                    "Plus de modeles ici : ecrivez vos propres questions ci-dessous. "
                    "Astuce : soyez precis sur le contexte, donnez un exemple concret, et "
                    "si la reponse ne convient pas, reformulez votre question pour l'affiner."
                )
                st.caption(f"Echanges realises : {progression_niveau3['messages_envoyes_niveau3']}/5")
                st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)

            niveau4_debloque = any(nom.startswith("Niveau 4") for nom in noms_debloques)
            niveau3_reellement_termine = not niveau3_debloque or progression_niveau3["niveau3_complete"]
            progression_niveau4 = (
                charger_progression_niveau4(utilisateur.get("id"))
                if (
                    progression_niveau1["niveau1_complete"]
                    and niveau2_reellement_termine
                    and niveau3_reellement_termine
                    and niveau4_debloque
                )
                else {"prompts_utilises_niveau4": [], "niveau4_complete": False}
            )

            if (
                progression_niveau1["niveau1_complete"]
                and niveau2_reellement_termine
                and niveau3_reellement_termine
                and niveau4_debloque
            ):
                if progression_niveau4["niveau4_complete"]:
                    st.markdown(
                        f"""<div style='background:{PRIMARY_YELLOW_LIGHT};border-left:4px solid {PRIMARY_YELLOW};
                                    border-radius:8px;padding:14px 16px;margin-bottom:12px;'>
                            <p style='font-size:15px;font-weight:600;margin:0;'>🏆 Maitrise AcademieIA</p>
                            <p style='font-size:13px;margin:4px 0 0;color:var(--text-secondary);'>
                                Vous avez termine tout le parcours ! Felicitations.
                            </p>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                    if PDF_ACTIF:
                        st.download_button(
                            "🏆 Telecharger mon certificat en PDF",
                            data=generer_pdf_certificat(
                                utilisateur.get("nom") or "Utilisateur",
                                profession_utilisateur,
                            ),
                            file_name="certificat_academieia.pdf",
                            mime="application/pdf",
                            key="telecharger_certificat_niveau4",
                            use_container_width=True,
                        )
                    else:
                        st.caption("Telechargement PDF indisponible : ajoutez 'fpdf2' a requirements.txt.")
                    st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)
                else:
                    st.markdown("##### 🏆 Niveau 4 — Maitrise")
                    afficher_lecon_niveau(4)
                    st.markdown(
                        "Cas d'usage avances : combinez l'IA avec vos autres outils. "
                        "Cliquez-en un pour le pre-remplir, modifiez-le si besoin, puis envoyez-le. "
                        "*Essayez-en au moins 3 differents pour obtenir votre certificat.*"
                    )
                    prompts_avances_niveau4 = [
                        f"Aide-moi a structurer un tableau Google Sheets pour suivre mon activite de {profession_utilisateur} (colonnes et formules utiles)",
                        f"Redige-moi un modele de document Google Docs reutilisable chaque semaine dans mon metier de {profession_utilisateur}",
                        f"Explique-moi comment automatiser une tache repetitive de mon metier de {profession_utilisateur} en combinant l'IA et un tableur",
                        f"Aide-moi a preparer un message pour expliquer a un collegue {profession_utilisateur} comment utiliser l'IA au quotidien",
                        f"Donne-moi 3 idees pour gagner encore plus de temps avec l'IA dans mon metier de {profession_utilisateur}",
                    ]
                    for index_avance, prompt_avance in enumerate(prompts_avances_niveau4):
                        deja_utilise = str(index_avance) in progression_niveau4["prompts_utilises_niveau4"]
                        libelle = f"✓ {prompt_avance}" if deja_utilise else prompt_avance
                        if st.button(libelle, key=f"prompt_avance_niveau4_{index_avance}", use_container_width=True):
                            st.session_state.question_assistant = prompt_avance
                            st.session_state.niveau4_prompt_choisi = index_avance
                            question_a_envoyer = prompt_avance
                    st.caption(f"Cas essayes : {len(set(progression_niveau4['prompts_utilises_niveau4']))}/3")
                    st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)

            message_progression = None
            if not progression_niveau1["niveau1_complete"]:
                message_progression = "Vous debutez : posez une question ou cliquez un exemple ci-dessus pour terminer le Niveau 1."
            elif niveau2_debloque and not progression_niveau2["niveau2_complete"]:
                nb = len(set(progression_niveau2["prompts_utilises_niveau2"]))
                message_progression = f"Niveau 2 en cours : {nb}/3 prompts essayes. Plus que {3 - nb} pour terminer !"
            elif niveau3_debloque and not progression_niveau3["niveau3_complete"]:
                nb = progression_niveau3["messages_envoyes_niveau3"]
                message_progression = f"Niveau 3 en cours : {nb}/5 echanges. Plus que {5 - nb} pour terminer !"
            elif niveau4_debloque and not progression_niveau4["niveau4_complete"]:
                nb = len(set(progression_niveau4["prompts_utilises_niveau4"]))
                message_progression = f"Niveau 4 en cours : {nb}/3 cas essayes. Plus que {3 - nb} pour obtenir votre certificat !"

            if message_progression:
                st.markdown(
                    f"""<div style='background:{PRIMARY_YELLOW_LIGHT};border-left:4px solid {PRIMARY_YELLOW};
                                border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px;'>{message_progression}</div>""",
                    unsafe_allow_html=True,
                )

            st.text_area("Posez votre question a l'assistant", key="question_assistant", placeholder="Ex : comment l'IA peut-elle m'aider dans mon metier ?")
            if st.button("Envoyer", key="btn_envoyer_question", use_container_width=True):
                question_a_envoyer = st.session_state.get("question_assistant", "").strip()

            if question_a_envoyer is not None:
                if not question_a_envoyer:
                    st.warning("Ecris ta question avant d'envoyer.")
                elif not GROQ_ACTIF:
                    st.info("Assistant IA pas encore configure : ajoutez GROQ_API_KEY dans les secrets.")
                elif quota_max is not None and questions_utilisees_aujourdhui >= quota_max:
                    st.error(
                        f"🚫 Vous avez atteint votre quota de {quota_max} questions aujourd'hui. "
                        f"Revenez demain, ou debloquez le niveau superieur pour continuer maintenant."
                    )
                else:
                    with st.spinner("L'assistant reflechit..."):
                        try:
                            reponse = repondre_assistant_ia(
                                question_a_envoyer, utilisateur.get("profession"), noms_debloques
                            )
                            st.markdown(
                                f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                                            border-radius:8px;padding:14px 16px;margin-top:8px;'>{reponse}</div>""",
                                unsafe_allow_html=True,
                            )
                            enregistrer_question_quota(utilisateur.get("id"), questions_utilisees_aujourdhui)
                            enregistrer_historique_question(utilisateur.get("id"), question_a_envoyer, reponse)
                            if quota_max is not None and questions_utilisees_aujourdhui + 1 >= quota_max:
                                st.warning(
                                    "⚠️ C'etait votre derniere question autorisee aujourd'hui. "
                                    "Debloquez le niveau superieur pour continuer sans limite."
                                )
                            elif quota_max is not None and questions_utilisees_aujourdhui + 2 >= quota_max:
                                st.warning(
                                    "⚠️ Il vous reste 1 question aujourd'hui. Debloquez le niveau "
                                    "superieur pour continuer sans limite."
                                )
                            if not progression_niveau1["niveau1_complete"]:
                                enregistrer_message_niveau1(
                                    utilisateur.get("id"),
                                    progression_niveau1["messages_envoyes_niveau1"],
                                )
                                st.success(
                                    "Bravo, vous avez fait vos premiers pas avec l'IA 🎉 "
                                    "Niveau 1 termine !"
                                )
                            elif st.session_state.get("niveau2_prompt_choisi") is not None:
                                enregistrer_prompt_niveau2(
                                    utilisateur.get("id"),
                                    st.session_state.niveau2_prompt_choisi,
                                    progression_niveau2["prompts_utilises_niveau2"],
                                )
                                nouveau_total = len(set(
                                    progression_niveau2["prompts_utilises_niveau2"]
                                    + [str(st.session_state.niveau2_prompt_choisi)]
                                ))
                                st.session_state.niveau2_prompt_choisi = None
                                if nouveau_total >= 3:
                                    st.success(
                                        "Vous maitrisez les bases de la demande precise 👏 "
                                        "Niveau 2 termine !"
                                    )
                            elif (
                                niveau3_debloque
                                and progression_niveau1["niveau1_complete"]
                                and niveau2_reellement_termine
                                and not progression_niveau3["niveau3_complete"]
                            ):
                                enregistrer_message_niveau3(
                                    utilisateur.get("id"),
                                    progression_niveau3["messages_envoyes_niveau3"],
                                )
                                if progression_niveau3["messages_envoyes_niveau3"] + 1 >= 5:
                                    st.success(
                                        "Vous etes autonome avec l'IA 🚀 Niveau 3 termine !"
                                    )
                            elif st.session_state.get("niveau4_prompt_choisi") is not None:
                                enregistrer_prompt_niveau4(
                                    utilisateur.get("id"),
                                    st.session_state.niveau4_prompt_choisi,
                                    progression_niveau4["prompts_utilises_niveau4"],
                                )
                                nouveau_total_niveau4 = len(set(
                                    progression_niveau4["prompts_utilises_niveau4"]
                                    + [str(st.session_state.niveau4_prompt_choisi)]
                                ))
                                st.session_state.niveau4_prompt_choisi = None
                                if nouveau_total_niveau4 >= 3:
                                    st.success(
                                        "Felicitations, vous avez termine tout le parcours AcademieIA 🏆 "
                                        "Votre certificat est disponible ci-dessus, rechargez la page pour le voir."
                                    )

                            if PDF_ACTIF:
                                st.download_button(
                                    "📄 Telecharger cette reponse en PDF",
                                    data=generer_pdf_texte(
                                        f"AcademieIA — Reponse de l'assistant ({profession_utilisateur})",
                                        f"Question :\n{question_a_envoyer}\n\nReponse :\n{reponse}",
                                    ),
                                    file_name="reponse_academieia.pdf",
                                    mime="application/pdf",
                                    key="telecharger_pdf_reponse",
                                )
                        except Exception as erreur:
                            st.error(f"L'assistant n'a pas pu repondre : {erreur}")

        else:
            with st.expander("Ressources gratuites : outils Google"):
                for cours in COURS_OUTILS_GOOGLE:
                    st.markdown(
                        f"""<div style='background:var(--surface-2, #F7F7F5);border:0.5px solid var(--border, #E5E4E1);
                                    border-radius:8px;padding:10px 12px;margin-bottom:8px;'>
                            <a href='{cours["url"]}' target='_blank' style='font-size:14px;font-weight:600;
                                color:{PRIMARY_BLUE};text-decoration:none;'>{cours["titre"]}</a>
                            <p style='font-size:12px;color:var(--text-secondary, #5f5e5a);margin:4px 0 0;'>{cours["description"]}</p>
                        </div>""",
                        unsafe_allow_html=True,
                    )

            st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)

            quiz_reussi = charger_quiz_reussi(utilisateur.get("id"))

            for index, niveau_actuel in enumerate(niveaux):
                numero_niveau_actuel = index + 1
                nom_niveau = niveau_actuel["nom"]
                debloque = nom_niveau in niveaux_debloques
                niveau_precedent_ok = index == 0 or (
                    niveaux[index - 1]["nom"] in niveaux_debloques and quiz_reussi.get(index, False)
                )

                if debloque:
                    st.markdown(
                        f"""<div style='background:#FDE8EB;border-left:4px solid {PRIMARY_BLUE};border-radius:8px;
                                    padding:12px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;'>
                            <span style='font-size:14px;font-weight:500;'>{nom_niveau}</span>
                            <span style='font-size:11px;background:{PRIMARY_BLUE};color:white;padding:3px 10px;border-radius:8px;'>Debloque</span>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                    if not quiz_reussi.get(numero_niveau_actuel, False):
                        quiz_vient_de_reussir = afficher_quiz_niveau(numero_niveau_actuel, utilisateur.get("id"))
                        if quiz_vient_de_reussir:
                            st.rerun()
                elif not niveau_precedent_ok:
                    st.markdown(
                        f"""<div style='background:var(--surface-2, #F1F1EF);border-left:4px solid var(--border, #D9D8D4);
                                    border-radius:8px;padding:12px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;opacity:0.7;'>
                            <span style='font-size:14px;font-weight:500;color:var(--text-secondary, #5f5e5a);'>🔒 {nom_niveau}</span>
                            <span style='font-size:11px;color:var(--text-secondary, #5f5e5a);'>Reussissez le quiz du niveau precedent</span>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""<div style='background:{PRIMARY_YELLOW_LIGHT};border-left:4px solid {PRIMARY_YELLOW};border-radius:8px;
                                    padding:12px 14px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;'>
                            <span style='font-size:14px;font-weight:500;'>{nom_niveau}</span>
                            <span style='font-size:11px;background:{PRIMARY_YELLOW};color:{PRIMARY_YELLOW_TEXT};padding:3px 10px;border-radius:8px;'>{niveau_actuel["prix"]}</span>
                        </div>""",
                        unsafe_allow_html=True,
                    )
                    with st.expander(f"Comment debloquer {nom_niveau} ?", key=f"expander_niveau_{index}"):
                        st.markdown("**1. Effectuez le paiement**")
                        cartes_numeros = "".join(
                            f"""<div style='background:var(--surface-2);border:0.5px solid var(--border);border-radius:8px;
                                        padding:10px 12px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;'>
                                <span style='font-size:13px;'>{op['operateur']}</span>
                                <span style='font-size:13px;font-weight:600;color:{PRIMARY_BLUE};'>{op['numero']}</span>
                            </div>"""
                            for op in NUMEROS_MOBILE_MONEY
                        )
                        st.markdown(cartes_numeros, unsafe_allow_html=True)

                        st.markdown("**2. Envoyez la preuve de paiement**")
                        st.markdown(
                            f"""<div style='background:#FDE8EB;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;'>
                                Capture d'ecran a envoyer sur WhatsApp au <strong>{CONTACT_ADMIN_WHATSAPP}</strong>
                            </div>""",
                            unsafe_allow_html=True,
                        )

                        st.markdown("**3. Suivi de la demande** *(optionnel)*")
                        reference = st.text_input(
                            "Reference de transaction", key=f"reference_paiement_{index}",
                            label_visibility="collapsed", placeholder="Reference de transaction (optionnel)",
                        )
                        with st.container(key=f"bouton_jaune_paiement_{index}"):
                            if st.button("J'ai envoye le paiement", key=f"btn_soumettre_paiement_{index}", use_container_width=True):
                                if SUPABASE_ACTIF:
                                    try:
                                        soumettre_demande_paiement(utilisateur.get("id"), nom_niveau, reference)
                                        st.success("Demande enregistree. L'administrateur va la traiter et vous envoyer un code.")
                                    except Exception as erreur:
                                        st.error(f"Impossible d'enregistrer la demande : {erreur}")
                                else:
                                    st.info("Mode demo : la demande ne peut pas etre enregistree sans Supabase configure.")

                        st.markdown("**4. Saisissez le code recu**")
                        code_saisi = st.text_input(
                            "Code d'acces", key=f"code_acces_saisi_{index}",
                            label_visibility="collapsed", placeholder="Code d'acces",
                        )
                        if st.button("Valider le code", key=f"btn_valider_code_{index}", use_container_width=True):
                            if not code_saisi:
                                st.error("Merci de saisir un code.")
                            elif SUPABASE_ACTIF:
                                try:
                                    resultat = valider_code_acces(code_saisi.strip(), utilisateur.get("id"))
                                    if resultat and str(resultat).startswith("ok"):
                                        st.success(f"{nom_niveau} debloque !")
                                        st.rerun()
                                    elif resultat == "deja_utilise":
                                        st.error("Ce code a deja ete utilise.")
                                    else:
                                        st.error("Code invalide.")
                                except Exception as erreur:
                                    st.error(f"Erreur lors de la validation : {erreur}")
                            else:
                                st.info("Mode demo : la validation de code necessite Supabase configure.")


def ecran_enseignant():
    with st.container(key="fond_connecte"):
        utilisateur = st.session_state.utilisateur_connecte
        profil = charger_profil_enseignant(utilisateur.get("id"))

        if not profil:
            st.markdown("##### Configuration de votre espace enseignant")
            st.caption("Renseignez ces informations une seule fois pour generer votre progression.")
            with st.form("form_config_enseignant"):
                matiere = st.text_input("Matiere enseignee", placeholder="Ex : Menuiserie aluminium")
                niveau_classe = st.text_input("Niveau / classe", placeholder="Ex : Terminale MSMA")
                etablissement = st.text_input("Etablissement (optionnel)")
                nb_semaines = st.number_input("Nombre de semaines dans l'annee scolaire", min_value=10, max_value=40, value=32)
                programme_pdf = st.file_uploader("Programme officiel (PDF, optionnel)", type=["pdf"])
                soumis = st.form_submit_button("Enregistrer et generer ma progression")

            if soumis:
                if not matiere or not niveau_classe:
                    st.error("Merci de renseigner au moins la matiere et le niveau.")
                elif not SUPABASE_ACTIF:
                    st.info("Mode demo : la configuration necessite Supabase configure.")
                else:
                    try:
                        programme_url = None
                        if programme_pdf is not None:
                            programme_url = uploader_programme_pdf(utilisateur.get("id"), programme_pdf)
                        enregistrer_profil_enseignant(
                            utilisateur.get("id"), matiere, niveau_classe, etablissement, nb_semaines, programme_url
                        )
                        st.session_state.declencher_generation_progression = True
                        st.rerun()
                    except Exception as erreur:
                        st.error(f"Impossible d'enregistrer votre profil : {erreur}")
            return

        progression = charger_derniere_progression(utilisateur.get("id"))

        if not progression or st.session_state.get("declencher_generation_progression"):
            st.markdown("##### Generation de votre progression annuelle")
            if not GROQ_ACTIF:
                st.info("Generation IA pas encore configuree : ajoutez GROQ_API_KEY dans les secrets.")
                return
            with st.spinner("Generation de la progression en cours (peut prendre une minute)..."):
                try:
                    contenu = generer_progression_ia(profil["matiere"], profil["niveau_classe"], profil["nb_semaines"])
                    progression = enregistrer_progression(utilisateur.get("id"), contenu)
                    st.session_state.declencher_generation_progression = False
                    st.success("Progression generee !")
                    st.rerun()
                except Exception as erreur:
                    st.error(f"Impossible de generer la progression : {erreur}")
                    return

        st.markdown(
            f"""<div style='background:#FDE8EB;border-radius:12px;padding:12px 14px;margin-bottom:1rem;'>
                <p style='font-size:13px;margin:0;'><strong>{profil['matiere']}</strong> — {profil['niveau_classe']}</p>
                <p style='font-size:12px;margin:4px 0 0;color:var(--text-secondary);'>{profil.get('etablissement') or ''}</p>
            </div>""",
            unsafe_allow_html=True,
        )

        contenu_progression = progression["contenu"]
        semaines_options = [f"Semaine {ligne['semaine']} — {ligne['theme']}" for ligne in contenu_progression]
        semaine_choisie_index = st.selectbox(
            "Choisir une semaine", options=range(len(contenu_progression)),
            format_func=lambda i: semaines_options[i], key="semaine_enseignant_choisie",
        )
        ligne_semaine = contenu_progression[semaine_choisie_index]

        st.markdown(
            f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                        border-radius:8px;padding:12px 14px;margin:10px 0;'>
                <p style='font-size:13px;margin:0;'><strong>Objectifs :</strong> {ligne_semaine.get('objectifs')}</p>
            </div>""",
            unsafe_allow_html=True,
        )

        col_cours, col_devoir = st.columns(2)
        with col_cours:
            if st.button("Generer le cours", key="btn_generer_cours", use_container_width=True):
                st.session_state["generation_en_cours"] = "cours"
        with col_devoir:
            if st.button("Generer le devoir", key="btn_generer_devoir", use_container_width=True):
                st.session_state["generation_en_cours"] = "devoir"

        type_a_generer = st.session_state.get("generation_en_cours")
        if type_a_generer:
            document_existant = charger_document_genere(
                utilisateur.get("id"), progression["id"], ligne_semaine["semaine"], type_a_generer
            )
            if document_existant:
                contenu_document = document_existant["contenu"]
            elif not GROQ_ACTIF:
                st.info("Generation IA pas encore configuree : ajoutez GROQ_API_KEY dans les secrets.")
                contenu_document = None
            else:
                with st.spinner(f"Generation du {type_a_generer} en cours..."):
                    try:
                        contenu_document = generer_document_cours_devoir(
                            type_a_generer, profil["matiere"], profil["niveau_classe"],
                            ligne_semaine["theme"], ligne_semaine["objectifs"],
                        )
                        enregistrer_document_genere(
                            utilisateur.get("id"), progression["id"], ligne_semaine["semaine"],
                            type_a_generer, contenu_document,
                        )
                    except Exception as erreur:
                        st.error(f"Impossible de generer le {type_a_generer} : {erreur}")
                        contenu_document = None

            if contenu_document:
                with st.container(border=True):
                    st.markdown(contenu_document)
                if PDF_ACTIF:
                    st.download_button(
                        f"Telecharger le {type_a_generer} en PDF",
                        data=generer_pdf_texte(f"{profil['matiere']} — {ligne_semaine['theme']}", contenu_document),
                        file_name=f"{type_a_generer}_semaine{ligne_semaine['semaine']}.pdf",
                        mime="application/pdf",
                        key=f"telecharger_{type_a_generer}_{ligne_semaine['semaine']}",
                    )


def entete_avec_deconnexion(titre_role):
    col_titre, col_bouton = st.columns([4, 1])
    with col_titre:
        if titre_role in ("admin", "super_admin"):
            couleur_fond = PRIMARY_YELLOW if titre_role == "super_admin" else PRIMARY_YELLOW_LIGHT
            couleur_texte = "#412402" if titre_role == "super_admin" else "#633806"
            st.markdown(
                f"### AcademieIA <span style='display:inline-block;background:{couleur_fond};"
                f"color:{couleur_texte};padding:2px 10px;border-radius:8px;font-size:12px;'>{titre_role}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"### AcademieIA <span class='badge'>{titre_role}</span>", unsafe_allow_html=True)
    with col_bouton:
        if st.button("Deconnexion", key="btn_logout"):
            st.session_state.utilisateur_connecte = None
            st.session_state.ecran = "accueil"
            st.rerun()


if st.session_state.utilisateur_connecte is None:
    if st.session_state.ecran == "accueil":
        ecran_accueil()
    else:
        ecran_authentification()
else:
    role = st.session_state.utilisateur_connecte["role"]
    nom = st.session_state.utilisateur_connecte["nom"]

    if role == "super_admin":
        entete_avec_deconnexion("super_admin")
        ecran_super_admin()
    elif role == "admin":
        entete_avec_deconnexion("admin")
        ecran_admin()
    elif role == "enseignant":
        entete_avec_deconnexion("enseignant")
        ecran_enseignant()
    else:
        entete_avec_deconnexion("utilisateur")
        ecran_utilisateur()
        
