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
        f"Tu es l'assistant pedagogique d'AcademieIA, une plateforme de formation pour des "
        f"professionnels ivoiriens du batiment (menuiserie aluminium, ebenisterie, et autres "
        f"metiers techniques). L'utilisateur exerce le metier suivant : {contexte_metier}. "
        f"Il a acces aux niveaux suivants : {contexte_niveaux}. Reponds de facon claire, concrete "
        f"et pratique, adaptee a son metier. Utilise des exemples chiffres quand c'est pertinent "
        f"(calculs de quantites, devis, etc.). Reponds en francais."
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

    col_tab1, col_tab2 = st.columns(2)
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

    st.markdown("<hr style='margin-top:0;'>", unsafe_allow_html=True)

    if st.session_state.onglet_utilisateur_actif == "assistant":
        noms_debloques = [n["nom"] for n in niveaux if n["nom"] in niveaux_debloques]
        niveaux_texte = " + ".join(noms_debloques) if noms_debloques else "Aucun niveau debloque"
        st.markdown(
            f"""<div style='background:var(--surface-2);border-radius:8px;padding:8px 12px;margin-bottom:12px;
                        font-size:12px;color:var(--text-secondary);'>
                Niveau actif : <strong style='color:{PRIMARY_BLUE};'>{niveaux_texte}</strong>
            </div>""",
            unsafe_allow_html=True,
        )
        st.text_area("Posez votre question a l'assistant", key="question_assistant", placeholder="Ex : comment calculer la quantite de profiles alu pour une baie de 3m x 2m ?")
        if st.button("Envoyer", key="btn_envoyer_question", use_container_width=True):
            question = st.session_state.get("question_assistant", "").strip()
            if not question:
                st.warning("Ecris ta question avant d'envoyer.")
            elif not GROQ_ACTIF:
                st.info("Assistant IA pas encore configure : ajoutez GROQ_API_KEY dans les secrets.")
            else:
                with st.spinner("L'assistant reflechit..."):
                    try:
                        reponse = repondre_assistant_ia(
                            question, utilisateur.get("profession"), noms_debloques
                        )
                        st.markdown(
                            f"""<div style='background:var(--surface-2, #F7F7F5);border-left:4px solid {PRIMARY_BLUE};
                                        border-radius:8px;padding:14px 16px;margin-top:8px;'>{reponse}</div>""",
                            unsafe_allow_html=True,
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
