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


def envoyer_message_support(user_id, auteur, contenu):
    """Ajoute un message dans le fil de discussion support d'un utilisateur.
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
    except Exception:
        pass


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

# ----------------------------------------------------------------------
# Configuration generale
# ----------------------------------------------------------------------
st.set_page_config(page_title="AcademieIA", page_icon="🔷", layout="centered")

PRIMARY_BLUE = "#185FA5"
PRIMARY_YELLOW = "#EF9F27"
PRIMARY_YELLOW_TEXT = "#412402"
PRIMARY_YELLOW_LIGHT = "#FAEEDA"

st.markdown(
    f"""
    <style>
    .stApp {{
        background: linear-gradient(180deg, {PRIMARY_YELLOW_LIGHT} 0%, #FFFFFF 320px);
    }}
    .stButton>button {{
        background-color: {PRIMARY_BLUE};
        color: white;
        border-radius: 8px;
        border: none;
    }}
    .badge {{
        display: inline-block;
        background-color: #E6F1FB;
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
    [class*="st-key-tab_niveaux_actif"] button {{
        background: transparent !important;
        color: {PRIMARY_YELLOW_TEXT} !important;
        border: none !important;
        border-bottom: 3px solid {PRIMARY_YELLOW} !important;
        border-radius: 0 !important;
        font-weight: 600 !important;
        box-shadow: none !important;
    }}
    [class*="st-key-tab_assistant_inactif"] button,
    [class*="st-key-tab_niveaux_inactif"] button {{
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

# Les 4 niveaux sont payants et se debloquent dans l'ordre : il faut avoir
# debloque le niveau precedent avant de pouvoir payer le suivant.
# Les intitules s'adaptent au metier saisi par l'utilisateur a l'inscription
# (champ texte libre) : on reconnait "menuiserie aluminium" et "ebenisterie",
# et on retombe sur un parcours generique pour les autres metiers.
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

# Ressources gratuites, accessibles a tous sans deblocage : liens vers les
# tutoriels officiels du Centre de formation Google Workspace (en francais).
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

# A adapter avec vos vrais numeros et montant
NUMEROS_MOBILE_MONEY = [
    {"operateur": "Wave", "numero": "01 02 93 93 80"},
]
CONTACT_ADMIN_WHATSAPP = "01 02 93 93 80"



# ----------------------------------------------------------------------
# Donnees fictives (a remplacer par Supabase)
# ----------------------------------------------------------------------
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
    st.session_state.utilisateur_connecte = None  # dict {nom, role, profession}

if "ecran" not in st.session_state:
    st.session_state.ecran = "accueil"  # accueil -> connexion / inscription -> dashboard

if "onglet_auth_par_defaut" not in st.session_state:
    st.session_state.onglet_auth_par_defaut = "Connexion"

if "niveau2_prompt_choisi" not in st.session_state:
    st.session_state.niveau2_prompt_choisi = None

if "niveau4_prompt_choisi" not in st.session_state:
    st.session_state.niveau4_prompt_choisi = None

# ----------------------------------------------------------------------
# Ecran : Accueil
# ----------------------------------------------------------------------
def ecran_accueil():
    col_gauche, col_centre, col_droite = st.columns([1, 2, 1])
    with col_centre:
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


# ----------------------------------------------------------------------
# Ecran : Connexion / Inscription
# ----------------------------------------------------------------------
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
        # Note : st.tabs ne permet pas de choisir l'onglet actif par defaut.
        # L'onglet souhaite (st.session_state.onglet_auth_par_defaut) sert
        # d'indication visuelle future si on remplace les tabs par des boutons.
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
            profession = st.text_input("Profession", key="signup_profession", placeholder="Ex : menuisier aluminium, plombier, electricien...")
            mdp_inscription = st.text_input("Mot de passe", key="signup_mdp", type="password")

            st.caption("Les comptes admin sont crees uniquement par un super administrateur.")

            with st.container(key="bouton_jaune_signup"):
                if st.button("Creer mon compte", key="btn_signup", use_container_width=True):
                    if not nom or not email_inscription or not profession or not mdp_inscription:
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
                                    "role": "utilisateur",
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
                            "role": "utilisateur",
                            "inscrit_le": str(date.today()),
                        }
                        st.session_state.utilisateurs = pd.concat(
                            [st.session_state.utilisateurs, pd.DataFrame([nouvelle_ligne])],
                            ignore_index=True,
                        )
                        st.success("Compte cree. Vous pouvez vous connecter.")


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



# ----------------------------------------------------------------------
# Ecran : Dashboard admin
# ----------------------------------------------------------------------
def ecran_admin():
    if st.session_state.get("erreur_supabase"):
        st.error(f"Erreur de connexion a Supabase : {st.session_state.erreur_supabase}")

    utilisateurs = st.session_state.utilisateurs
    seulement_utilisateurs = utilisateurs[utilisateurs["role"] == "utilisateur"]

    carte_metrique("Utilisateurs", len(seulement_utilisateurs), PRIMARY_YELLOW)

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
                couleur_fond = "var(--surface-2, #F7F7F5)" if est_utilisateur else "#E6F1FB"
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


# ----------------------------------------------------------------------
# Ecran : Dashboard super_admin
# ----------------------------------------------------------------------
def ecran_super_admin():
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


# ----------------------------------------------------------------------
# Ecran : espace utilisateur (niveaux gratuit / payant)
# ----------------------------------------------------------------------
def ecran_utilisateur():
    utilisateur = st.session_state.utilisateur_connecte
    niveaux_debloques = charger_niveaux_utilisateur(utilisateur.get("id"))

    st.markdown(
        f"""<div style='background:#E6F1FB;border-radius:12px;padding:12px 14px;margin-bottom:1rem;'>
            <p style='font-size:13px;margin:0;'>Bienvenue, <strong>{utilisateur.get('nom')}</strong></p>
            <p style='font-size:12px;margin:4px 0 0;color:var(--text-secondary);'>{utilisateur.get('profession') or '-'}</p>
        </div>""",
        unsafe_allow_html=True,
    )

    if "onglet_utilisateur_actif" not in st.session_state:
        st.session_state.onglet_utilisateur_actif = "assistant"

    niveaux = obtenir_niveaux(utilisateur.get("profession"))

    col_tab1, col_tab2, col_tab3 = st.columns(3)
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
        cle = "tab_support_actif" if st.session_state.onglet_utilisateur_actif == "support" else "tab_support_inactif"
        with st.container(key=cle):
            if st.button("Support", key="btn_onglet_support", use_container_width=True):
                st.session_state.onglet_utilisateur_actif = "support"
                st.rerun()

    st.markdown("<hr style='margin-top:0;'>", unsafe_allow_html=True)

    if st.session_state.onglet_utilisateur_actif == "support":
        st.markdown("##### 💬 Support — echangez avec un admin")
        messages_utilisateur = charger_messages_utilisateur(utilisateur.get("id"))
        if not messages_utilisateur:
            st.caption("Aucun message pour l'instant. Ecrivez votre premiere question ci-dessous.")
        for message in messages_utilisateur:
            est_utilisateur = message.get("auteur") == "utilisateur"
            couleur_fond = "#E6F1FB" if est_utilisateur else "var(--surface-2, #F7F7F5)"
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

        # --- Niveau 1 : prise en main --------------------------------------
        progression_niveau1 = charger_progression_niveau1(utilisateur.get("id"))
        profession_utilisateur = utilisateur.get("profession") or "votre metier"
        question_a_envoyer = None

        if not progression_niveau1["niveau1_complete"]:
            st.markdown("##### 🎓 Niveau 1 — Prise en main")
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
        # ---------------------------------------------------------------------

        # --- Niveau 2 : usage guide (payant, apres le Niveau 1) ------------
        niveau2_debloque = any(nom.startswith("Niveau 2") for nom in noms_debloques)
        progression_niveau2 = (
            charger_progression_niveau2(utilisateur.get("id"))
            if progression_niveau1["niveau1_complete"] and niveau2_debloque
            else {"prompts_utilises_niveau2": [], "niveau2_complete": True}
        )

        if progression_niveau1["niveau1_complete"] and niveau2_debloque and not progression_niveau2["niveau2_complete"]:
            st.markdown("##### 🚀 Niveau 2 — Usage guide")
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
            st.caption(f"Prompts essayes : {len(set(progression_niveau2['prompts_utilises_niveau2']))}/3")
            st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)
        # ---------------------------------------------------------------------

        # --- Niveau 3 : autonomie (payant, apres le Niveau 2) --------------
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
            st.markdown(
                "Plus de modeles ici : ecrivez vos propres questions ci-dessous. "
                "Astuce : soyez precis sur le contexte, donnez un exemple concret, et "
                "si la reponse ne convient pas, reformulez votre question pour l'affiner."
            )
            st.caption(f"Echanges realises : {progression_niveau3['messages_envoyes_niveau3']}/5")
            st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)
        # ---------------------------------------------------------------------

        # --- Niveau 4 : maitrise (payant, dernier niveau) -------------------
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
                st.caption(f"Cas essayes : {len(set(progression_niveau4['prompts_utilises_niveau4']))}/3")
                st.markdown("<hr style='margin:12px 0;'>", unsafe_allow_html=True)
        # ---------------------------------------------------------------------

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

        for index, niveau_actuel in enumerate(niveaux):
            nom_niveau = niveau_actuel["nom"]
            debloque = nom_niveau in niveaux_debloques
            niveau_precedent_ok = index == 0 or niveaux[index - 1]["nom"] in niveaux_debloques

            if debloque:
                st.markdown(
                    f"""<div style='background:#E6F1FB;border-left:4px solid {PRIMARY_BLUE};border-radius:8px;
                                padding:12px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;'>
                        <span style='font-size:14px;font-weight:500;'>{nom_niveau}</span>
                        <span style='font-size:11px;background:{PRIMARY_BLUE};color:white;padding:3px 10px;border-radius:8px;'>Debloque</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
            elif not niveau_precedent_ok:
                st.markdown(
                    f"""<div style='background:var(--surface-2, #F1F1EF);border-left:4px solid var(--border, #D9D8D4);
                                border-radius:8px;padding:12px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;opacity:0.7;'>
                        <span style='font-size:14px;font-weight:500;color:var(--text-secondary, #5f5e5a);'>🔒 {nom_niveau}</span>
                        <span style='font-size:11px;color:var(--text-secondary, #5f5e5a);'>Terminez le niveau precedent</span>
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
                        f"""<div style='background:#E6F1FB;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;'>
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


# ----------------------------------------------------------------------
# Routage principal
# ----------------------------------------------------------------------
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
    else:
        entete_avec_deconnexion("utilisateur")
        ecran_utilisateur()
