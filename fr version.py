# -*- coding: utf-8 -*-  
import sys
import re
import datetime
import hashlib
import mysql.connector
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.binary import Binary 
import base64 
import io 

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QLineEdit,
                            QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton,
                            QStackedWidget, QComboBox, QDateEdit, QTextEdit,
                            QListWidget, QListWidgetItem, QMessageBox, QGroupBox,
                            QScrollArea, QSizePolicy, QSpacerItem, QFileDialog,
                            QDialog, QDialogButtonBox)
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPixmap
from PyQt5.QtCore import Qt, QDate, QBuffer, QIODevice, QTimer, QSize 


# Variables globales pour les connexions aux bases de données
mysql_connection = None
mongo_client = None
mongo_db = None

# Configuration de la base de données
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Mohamed@mysql', # Attention : Mot de passe en clair
    'database': 'tawdrlikDB'
}

MONGODB_URI = "mongodb://localhost:27017/"
MONGODB_DB = "tawdrlikDB"

# Constantes de style de l'application
PRIMARY_COLOR = "#3BAFDA"
BACKGROUND_COLOR = "#F9FAFB"
ACCENT_COLOR = "#1C3D5A"
FONT_FAMILY = "Arial"


# --- Fonctions de connexion à la base de données ---

def connect_to_mysql():
    global mysql_connection
    if mysql_connection and mysql_connection.is_connected():
        return True # Déjà connecté
    try:
        mysql_connection = mysql.connector.connect(**MYSQL_CONFIG, autocommit=False) # Désactiver l'autocommit pour les transactions
        # Tester la connexion
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()
        print("MySQL connecté avec succès")
        return True
    except mysql.connector.Error as err:
        print(f"Erreur MySQL : {err}")
        QMessageBox.critical(None, "Erreur de base de données", f"Échec de la connexion MySQL : {err}")
        mysql_connection = None # S'assurer qu'il est None en cas d'échec
        return False

def connect_to_mongodb():
    global mongo_client, mongo_db
    if mongo_client is not None and mongo_db is not None:
         try:
              mongo_client.admin.command('ping') # Vérifier si la connexion est toujours active
              return True
         except Exception:
              print("Connexion MongoDB perdue, tentative de reconnexion...")
              mongo_client = None
              mongo_db = None
              # Passe à la logique de reconnexion
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000) # Ajouter un délai d'attente
        # La commande ismaster est peu coûteuse et ne nécessite pas d'authentification.
        mongo_client.admin.command('ismaster') # Vérifier la connexion
        mongo_db = mongo_client[MONGODB_DB]
        print("MongoDB connecté avec succès")
        return True
    except Exception as e:
        print(f"Erreur MongoDB : {e}")
        QMessageBox.critical(None, "Erreur de base de données", f"Échec de la connexion MongoDB : {e}")
        mongo_client = None
        mongo_db = None
        return False

def hash_password(password):
    """Hacher un mot de passe en utilisant SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

# --- Fonctions d'authentification utilisateur ---

def register_user(username, email, password):
    """Enregistrer un nouvel utilisateur dans la base de données MySQL"""
    if not connect_to_mysql():
        return False, "Base de données non connectée"
    cursor = None 
    try:
        cursor = mysql_connection.cursor()
        hashed_password = hash_password(password)

        # Vérifier si l'email existe déjà 
        cursor.execute("SELECT id_utilisateur FROM utilisateurs WHERE email = %s", (email,))
        if cursor.fetchone():
            return False, "Email déjà enregistré"

        # Vérifier si le nom d'utilisateur existe déjà
        cursor.execute("SELECT id_utilisateur FROM utilisateurs WHERE nom_utilisateur = %s", (username,))
        if cursor.fetchone():
            return False, "Nom d'utilisateur déjà pris"

        # Insérer le nouvel utilisateur
        cursor.execute(
            "INSERT INTO utilisateurs (nom_utilisateur, email, mot_de_passe) VALUES (%s, %s, %s)",
            (username, email, hashed_password)
        )
        mysql_connection.commit() 
        return True, "Inscription réussie !"
    
    except mysql.connector.Error as err:
        
        print(f"Erreur d'inscription : {err}")
        mysql_connection.rollback() # Annuler les changements en cas d'erreur 
        
        return False, f"Échec de l'inscription : {err}"
    finally:
        if cursor:
            cursor.close()

def login_user(email, password):
    """Authentifier un utilisateur par rapport à la base de données MySQL"""
    if not connect_to_mysql():
        return False, "Base de données non connectée"
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True) # Obtenir les résultats sous forme de dict
        hashed_password = hash_password(password)

        cursor.execute(
            "SELECT id_utilisateur, nom_utilisateur, email FROM utilisateurs WHERE email = %s AND mot_de_passe = %s",
            (email, hashed_password)
        )
        user = cursor.fetchone()

        if user:
            return True, user
        else:
            return False, "Email ou mot de passe invalide"
        
    except mysql.connector.Error as err:
        print(f"Erreur de connexion : {err}")
        return False, f"Échec de la connexion : {err}"
    finally:
        if cursor:
            cursor.close()

def save_item(user_id, title, category, location, date, status, description, image_data=None):
    """Sauvegarder les métadonnées de l'objet dans MySQL et les détails (description + image) dans MongoDB"""
    if not connect_to_mysql() or not connect_to_mongodb():
        return False, "Échec de la connexion à la base de données"

    mongo_id_obj = None
    mongo_id_str = None 
    cursor = None

    try:
        # 1. Sauvegarder la description et l'image dans MongoDB
        
        mongo_image_data = Binary(image_data) if image_data else None
        mongo_result = mongo_db.items_detail.insert_one({
            "description": description,
            "image": mongo_image_data 
        })
        mongo_id_obj = mongo_result.inserted_id
        mongo_id_str = str(mongo_id_obj)

        # 2. Sauvegarder les métadonnées dans MySQL, en liant au document MongoDB
        
        cursor = mysql_connection.cursor()
        cursor.execute(
            """INSERT INTO objets (id_utilisateur_proprietaire, titre, categorie, lieu, date_evenement, statut_objet, id_mongo_details, description_meta)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, title, category, location, date, status, mongo_id_str, description)
        )
        mysql_connection.commit()
        return True, "Objet sauvegardé avec succès !"

    except Exception as e:
        print(f"Erreur lors de la sauvegarde de l'objet : {e}")
        
        # Logique de rollback : Si MySQL échoue après l'insertion MongoDB, supprimer le doc MongoDB
        
        if mongo_id_obj:
            try:
                mongo_db.items_detail.delete_one({"_id": mongo_id_obj})
                print(f"Nettoyage de l'entrée MongoDB {mongo_id_str} en raison d'une erreur.")
            except Exception as mongo_del_err:
                print(f"Erreur lors du nettoyage de l'entrée MongoDB {mongo_id_str}: {mongo_del_err}")
        try:
            mysql_connection.rollback()
        except Exception as rollback_err:
            print(f"Erreur lors de l'annulation de la transaction MySQL : {rollback_err}")

        return False, f"Échec de la sauvegarde de l'objet : {e}"
    finally:
        if cursor:
            cursor.close()

def get_all_items(filter_category=None, filter_location=None, include_recovered=False):
    
    """Récupérer les objets (excluant les récupérés par défaut), joindre avec l'utilisateur, récupérer les détails de MongoDB"""
    
    if not connect_to_mysql() or not connect_to_mongodb():
        print("Échec de la connexion à la base de données dans get_all_items")
        return []

    items = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)

        query = """
        SELECT o.id_objet, o.id_utilisateur_proprietaire, o.titre, o.categorie, o.lieu, o.date_evenement, o.statut_objet, o.id_mongo_details, o.date_signalement,
               u.nom_utilisateur AS proprietaire_nom_utilisateur
        FROM objets o
        JOIN utilisateurs u ON o.id_utilisateur_proprietaire = u.id_utilisateur
        """

        params = []
        conditions = []

        # Exclure les objets récupérés sauf indication contraire
        
        if not include_recovered:
            conditions.append("o.statut_objet != %s") 
            params.append('recovered') 

        if filter_category and filter_category != "Toutes les catégories": 
            conditions.append("o.categorie = %s")
            params.append(filter_category)

        if filter_location and filter_location != "Tous les lieux": 
            conditions.append("o.lieu = %s")
            params.append(filter_location)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY o.statut_objet, o.date_evenement DESC, o.date_signalement DESC"

        cursor.execute(query, tuple(params)) 
        items_mysql = cursor.fetchall()

        # Récupérer les détails de MongoDB pour chaque objet
        for item_mysql in items_mysql:
            mongo_id_str = item_mysql.get('id_mongo_details')
            description = 'Détails indisponibles'
            image_data = None
            if mongo_id_str:
                try:
                    mongo_object_id = ObjectId(mongo_id_str)
                    item_detail = mongo_db.items_detail.find_one({"_id": mongo_object_id})
                    if item_detail:
                        description = item_detail.get('description', 'Aucune description trouvée')
                        image_data = item_detail.get('image') 
                    else:
                        print(f"Aucun document MongoDB trouvé pour mongo_id : {mongo_id_str}")
                        description = 'Détails manquants dans le stockage secondaire'
                except Exception as e:
                    print(f"Erreur lors de la récupération/analyse du document MongoDB ({mongo_id_str}): {e}")
                    description = 'Erreur lors de la récupération des détails'

            item_mysql['description'] = description
            item_mysql['image_data'] = image_data
            items.append(item_mysql) 

        return items
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération des objets depuis MySQL : {e}")
        return []
    except Exception as e:
        print(f"Une erreur s'est produite lors de la récupération des objets : {e}")
        return items 
    finally:
        if cursor:
            cursor.close()


def get_user_items(user_id):
    """Obtenir les objets postés par un utilisateur spécifique, y compris les récupérés, récupérer les détails de MongoDB"""
    if not connect_to_mysql() or not connect_to_mongodb():
        print("Échec de la connexion à la base de données dans get_user_items") 
        return []

    items = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT o.id_objet, o.id_utilisateur_proprietaire, o.titre, o.categorie, o.lieu, o.date_evenement, o.statut_objet, o.id_mongo_details, o.date_signalement,
                      u.nom_utilisateur AS proprietaire_nom_utilisateur
               FROM objets o
               JOIN utilisateurs u ON o.id_utilisateur_proprietaire = u.id_utilisateur
               WHERE o.id_utilisateur_proprietaire = %s
               ORDER BY o.date_signalement DESC""",
            (user_id,)
        )
        items_mysql = cursor.fetchall()

        # Récupérer les détails de MongoDB
        
        for item_mysql in items_mysql:
            mongo_id_str = item_mysql.get('id_mongo_details')
            description = 'Détails indisponibles'
            image_data = None
            if mongo_id_str: 
                try:
                    mongo_object_id = ObjectId(mongo_id_str)
                    item_detail = mongo_db.items_detail.find_one({"_id": mongo_object_id})
                    if item_detail:
                        description = item_detail.get('description', 'Aucune description trouvée')
                        image_data = item_detail.get('image') # BSON Binary ou None
                    else:
                        print(f"Aucun document MongoDB trouvé pour l'objet utilisateur mongo_id : {mongo_id_str}")
                        description = 'Détails manquants dans le stockage secondaire'
                except Exception as e:
                    print(f"Erreur lors de la récupération/analyse du document MongoDB ({mongo_id_str}) pour l'objet utilisateur : {e}")
                    description = 'Erreur lors de la récupération des détails'

            item_mysql['description'] = description
            item_mysql['image_data'] = image_data
            items.append(item_mysql)

        return items
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération des objets utilisateur depuis MySQL : {e}")
        return []
    except Exception as e:
        print(f"Une erreur s'est produite lors de la récupération des objets utilisateur : {e}")
        return items 
    finally:
        if cursor:
            cursor.close()

def get_item_owner(item_id):
    """Obtenir le user_id du propriétaire de l'objet."""
    if not connect_to_mysql():
        print("Échec de la connexion à la base de données dans get_item_owner")
        return None
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT id_utilisateur_proprietaire FROM objets WHERE id_objet = %s", (item_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération du propriétaire de l'objet : {e}")
        return None
    finally:
        if cursor:
            cursor.close()

def get_unique_categories():
    """Obtenir une liste des catégories uniques de la table items"""
    if not connect_to_mysql(): return ["Toutes les catégories"]
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT DISTINCT categorie FROM objets WHERE categorie IS NOT NULL AND categorie != '' ORDER BY categorie")
        categories = [row[0] for row in cursor.fetchall()]
        return ["Toutes les catégories"] + categories
    except mysql.connector.Error as e: 
        print(f"Erreur lors de la récupération des catégories : {e}")
        return ["Toutes les catégories"] 
    finally:
        if cursor:
            cursor.close()

def get_unique_locations():
    """Obtenir une liste des lieux uniques de la table items"""
    if not connect_to_mysql(): return ["Tous les lieux"]
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT DISTINCT lieu FROM objets WHERE lieu IS NOT NULL AND lieu != '' ORDER BY lieu")
        locations = [row[0] for row in cursor.fetchall()] 
        return ["Tous les lieux"] + locations
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération des lieux : {e}")
        return ["Tous les lieux"]
    finally:
        if cursor:
            cursor.close()


# --- Fonctions de gestion des réclamations ---

def submit_claim(item_id, claimant_id, reason, evidence_image_data=None):
    """Soumettre une réclamation pour un objet."""
    if not connect_to_mysql() or not connect_to_mongodb():
        return False, "Échec de la connexion à la base de données"

    mongo_detail_id_obj = None
    mongo_detail_id_str = None
    cursor = None

    try:
        if evidence_image_data: 
            mongo_result = mongo_db.claims_detail.insert_one({
                "evidence_image": Binary(evidence_image_data),
                "notes": f"Preuve pour la réclamation sur l'objet {item_id} par l'utilisateur {claimant_id}" 
            })
            mongo_detail_id_obj = mongo_result.inserted_id
            mongo_detail_id_str = str(mongo_detail_id_obj)

        # 2. Sauvegarder les détails de la réclamation dans MySQL
        cursor = mysql_connection.cursor()
        cursor.execute(
            """INSERT INTO reclamations (id_objet_reclame, id_utilisateur_reclamant, motif_reclamation, statut_reclamation, id_mongo_preuve, date_soumission_reclamation)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (item_id, claimant_id, reason, 'pending', mongo_detail_id_str, datetime.datetime.now())
        ) 

        mysql_connection.commit()
        return True, "Réclamation soumise avec succès !"

    except Exception as e:
        print(f"Erreur lors de la soumission de la réclamation : {e}")
        if mongo_detail_id_obj: 
            try: 
                mongo_db.claims_detail.delete_one({"_id": mongo_detail_id_obj})
                print(f"Nettoyage du détail de réclamation MongoDB {mongo_detail_id_str} en raison d'une erreur.")
            except Exception as mongo_del_err:
                print(f"Erreur lors du nettoyage du détail de réclamation MongoDB {mongo_detail_id_str}: {mongo_del_err}")
        try:
            mysql_connection.rollback()
        except Exception as rollback_err:
            print(f"Erreur lors de l'annulation de la transaction MySQL : {rollback_err}")

        return False, f"Échec de la soumission de la réclamation : {e}"
    finally:
        if cursor:
            cursor.close() 
def get_claims_for_item(item_id):
    """Récupérer toutes les réclamations pour un objet spécifique, en joignant avec les infos de l'utilisateur réclamant."""
    if not connect_to_mysql():
        print("Échec de la connexion à la base de données dans get_claims_for_item")
        return []
    claims = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        query = """
        SELECT r.id_reclamation AS claim_id, r.id_objet_reclame, r.id_utilisateur_reclamant, r.motif_reclamation, r.statut_reclamation AS claim_status,
               r.id_mongo_preuve, r.date_soumission_reclamation AS claim_created_at,
               u.nom_utilisateur AS claimant_username
        FROM reclamations r
        JOIN utilisateurs u ON r.id_utilisateur_reclamant = u.id_utilisateur
        WHERE r.id_objet_reclame = %s
        ORDER BY r.date_soumission_reclamation DESC
        """
        cursor.execute(query, (item_id,)) 
        claims_mysql = cursor.fetchall()

        # Récupérer facultativement les données d'image de preuve de MongoDB pour chaque réclamation
        for claim in claims_mysql:
            mongo_detail_id_str = claim.get('id_mongo_preuve')
            evidence_image_data = None
            if mongo_detail_id_str:
                try:
                    claim_detail = mongo_db.claims_detail.find_one({"_id": ObjectId(mongo_detail_id_str)})
                    if claim_detail:
                        evidence_image_data = claim_detail.get('evidence_image')
                except Exception as e:
                    print(f"Erreur lors de la récupération du détail de la réclamation ({mongo_detail_id_str}): {e}")
            claim['evidence_image_data'] = evidence_image_data
            claims.append(claim)

        return claims
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération des réclamations pour l'objet depuis MySQL : {e}")
        return []
    except Exception as e:
        print(f"Une erreur s'est produite lors de la récupération des réclamations pour l'objet : {e}")
        return claims 
    finally:
        if cursor:
            cursor.close()


def get_claims_by_claimant(claimant_id):
    """Récupérer toutes les réclamations faites par un utilisateur spécifique, en joignant avec les infos de l'objet."""
    if not connect_to_mysql():
        print("Échec de la connexion à la base de données dans get_claims_by_claimant")
        return []
    claims = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        query = """
        SELECT r.id_reclamation AS claim_id, r.id_objet_reclame, r.id_utilisateur_reclamant, r.motif_reclamation, r.statut_reclamation AS claim_status,
               r.id_mongo_preuve, r.date_soumission_reclamation AS claim_created_at,
               o.titre AS item_title, o.statut_objet AS item_status, o.id_mongo_details AS item_mongo_id
        FROM reclamations r
        JOIN objets o ON r.id_objet_reclame = o.id_objet
        WHERE r.id_utilisateur_reclamant = %s
        ORDER BY r.date_soumission_reclamation DESC 
        """
        cursor.execute(query, (claimant_id,))
        claims_mysql = cursor.fetchall()

        # Récupérer les détails (image de l'objet, image de preuve de la réclamation) de MongoDB
        for claim in claims_mysql:
            mongo_detail_id_str = claim.get('id_mongo_preuve')
            evidence_image_data = None
            if mongo_detail_id_str:
                try:
                    claim_detail = mongo_db.claims_detail.find_one({"_id": ObjectId(mongo_detail_id_str)})
                    if claim_detail:
                        evidence_image_data = claim_detail.get('evidence_image')
                except Exception as e:
                    print(f"Erreur lors de la récupération du détail de la réclamation ({mongo_detail_id_str}): {e}")
            claim['evidence_image_data'] = evidence_image_data

            # Récupérer l'image de l'objet
            item_mongo_id_str = claim.get('item_mongo_id') 
            item_image_data = None
            if item_mongo_id_str:
                 try:
                     item_detail = mongo_db.items_detail.find_one({"_id": ObjectId(item_mongo_id_str)})
                     if item_detail:
                         item_image_data = item_detail.get('image')
                 except Exception as e:
                      print(f"Erreur lors de la récupération du détail de l'objet pour la réclamation ({item_mongo_id_str}): {e}")
            claim['item_image_data'] = item_image_data 

            claims.append(claim)

        return claims
    except mysql.connector.Error as e:
        print(f"Erreur lors de la récupération des réclamations par réclamant depuis MySQL : {e}")
        return []
    except Exception as e:
        print(f"Une erreur s'est produite lors de la récupération des réclamations par réclamant : {e}")
        return claims 
    finally:
        if cursor:
            cursor.close()


def update_claim_status(claim_id, new_status):
    """Mettre à jour le statut d'une réclamation spécifique."""
    if not connect_to_mysql():
        return False, "Échec de la connexion à la base de données"
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute(
            "UPDATE reclamations SET statut_reclamation = %s WHERE id_reclamation = %s",
            (new_status, claim_id) 
        )
        mysql_connection.commit()
        # Traduire les statuts dans le message
        status_fr = {'pending': 'en attente', 'accepted': 'acceptée', 'rejected': 'rejetée', 'recovered': 'récupéré'}
        return True, f"Statut de la réclamation {claim_id} mis à jour à {status_fr.get(new_status, new_status)}"
    except mysql.connector.Error as err:
        print(f"Erreur lors de la mise à jour du statut de la réclamation : {err}")
        mysql_connection.rollback()
        return False, f"Échec de la mise à jour du statut de la réclamation : {err}"
    finally:
        if cursor:
            cursor.close()


def accept_claim(claim_id, item_id):
    """Accepter une réclamation : mettre à jour le statut de la réclamation, le statut de l'objet, rejeter les autres réclamations en attente."""
    status_accepted = 'accepted' # ou 'acceptee'
    status_recovered = 'recovered' # ou 'recupere'
    status_rejected = 'rejected' # ou 'rejetee'
    status_pending = 'pending' # ou 'en_attente'    

    if not connect_to_mysql():
        return False, "Échec de la connexion à la base de données"
    cursor = None
    try:
        cursor = mysql_connection.cursor()

        # 1. Mettre à jour le statut de la réclamation 'acceptée'
        cursor.execute("UPDATE reclamations SET statut_reclamation = %s WHERE id_reclamation = %s", ('accepted', claim_id))
        if cursor.rowcount == 0:
            raise Exception(f"ID de réclamation {claim_id} non trouvé.")

        # 2. Mettre à jour le statut de l'objet à 'récupéré'
        cursor.execute("UPDATE objets SET statut_objet = %s WHERE id_objet = %s", ('recovered', item_id))
        if cursor.rowcount == 0: 
             raise Exception(f"ID d'objet {item_id} non trouvé ou déjà récupéré.") 

        # 3. Rejeter toutes les autres réclamations *en attente* pour le même objet 
        cursor.execute(
            "UPDATE reclamations SET statut_reclamation = %s WHERE id_objet_reclame = %s AND statut_reclamation = %s AND id_reclamation != %s",
            ('rejected', item_id, 'pending', claim_id)
        )
        rejected_count = cursor.rowcount 

        mysql_connection.commit()
        return True, f"Réclamation {claim_id} acceptée. Objet {item_id} marqué comme récupéré. {rejected_count} autres réclamations en attente rejetées."

    except Exception as err: 
        print(f"Erreur lors de l'acceptation de la réclamation : {err}")
        mysql_connection.rollback()
        return False, f"Échec de l'acceptation de la réclamation : {err}"
    finally:
        if cursor:
            cursor.close()


def reject_claim(claim_id):
    """Rejeter une réclamation spécifique."""
    return update_claim_status(claim_id, 'rejected') # ou 'rejetee'


# --- Classes UI PyQt5 ---

class ClaimDialog(QDialog):
    """Dialogue pour soumettre une réclamation."""
    def __init__(self, item_id, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.selected_evidence_path = None
        self.evidence_image_data = None

        self.setWindowTitle("Soumettre une réclamation")
        self.setMinimumWidth(450)
        self.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # Champ Raison
        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("Expliquez pourquoi vous pensez que cet objet est le vôtre...")
        self.reason_edit.setMinimumHeight(100)
        self.reason_edit.setStyleSheet("padding: 8px; border: 1px solid #ccc; border-radius: 4px; background-color: white;")
        form_layout.addRow(QLabel("<b>Raison de la réclamation :</b>*"), self.reason_edit)

        # Image de preuve 
        evidence_layout = QHBoxLayout()
        self.select_evidence_button = QPushButton(QIcon.fromTheme("insert-image"), " Sélectionner une image de preuve ...")
        self.select_evidence_button.setStyleSheet(f"""
            QPushButton {{ background-color: #e0e0e0; color: #333; padding: 8px 12px;
                           border-radius: 5px; border: none; font-size: 13px;}}
            QPushButton:hover {{ background-color: #d5d5d5; }}
        """)
        self.select_evidence_button.setCursor(Qt.PointingHandCursor)
        self.select_evidence_button.clicked.connect(self.select_evidence_file)
        self.evidence_preview_label = QLabel("Aucune preuve sélectionnée.")
        self.evidence_preview_label.setStyleSheet("font-style: italic; color: #777; margin-left: 10px;")
        self.evidence_preview_label.setMinimumWidth(150)

        evidence_layout.addWidget(self.select_evidence_button)
        evidence_layout.addWidget(self.evidence_preview_label)
        evidence_layout.addStretch()
        form_layout.addRow(QLabel("<b>Preuve :</b>"), evidence_layout)

        layout.addLayout(form_layout)

        # Boutons de dialogue (Soumettre, Annuler)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("Soumettre la réclamation")
        button_box.button(QDialogButtonBox.Ok).setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 8px 20px; border-radius: 5px; font-weight: bold;")
        button_box.button(QDialogButtonBox.Cancel).setText("Annuler") 
        button_box.button(QDialogButtonBox.Cancel).setStyleSheet("background-color: #aaa; color: white; padding: 8px 20px; border-radius: 5px;")

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def select_evidence_file(self):
        """Ouvrir une boîte de dialogue pour sélectionner une image de preuve."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Sélectionner une image de preuve", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.gif)", options=options)
        if file_path:
            try:
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    raise ValueError("Fichier image invalide")

                with open(file_path, 'rb') as f:
                    self.evidence_image_data = f.read()
                    if len(self.evidence_image_data) > 16 * 1024 * 1024: # Vérifier la taille (16 Mo)
                        QMessageBox.warning(self, "Image trop grande", "L'image de preuve doit faire moins de 16 Mo.")
                        self.evidence_image_data = None
                        self.selected_evidence_path = None
                        self.evidence_preview_label.setText("Image trop grande.")
                        self.evidence_preview_label.setPixmap(QPixmap()) 
                        return

                self.selected_evidence_path = file_path 
                preview_pixmap = pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.evidence_preview_label.setPixmap(preview_pixmap)
                self.evidence_preview_label.setToolTip(file_path)

            except Exception as e:
                QMessageBox.warning(self, "Erreur d'image", f"Impossible de charger ou lire l'image : {e}")
                self.selected_evidence_path = None
                self.evidence_image_data = None
                self.evidence_preview_label.setText("Erreur chargement image.")
                self.evidence_preview_label.setPixmap(QPixmap()) 

    def get_claim_data(self):
        """Retourner la raison de la réclamation et les données de l'image."""
        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Informations manquantes", "Veuillez fournir une raison pour votre réclamation.")
            return None
        return reason, self.evidence_image_data 


class TawdrlikApp(QMainWindow):
    def __init__(self):
        super().__init__()
        if not connect_to_mysql() or not connect_to_mongodb():
            QMessageBox.critical(self, "Erreur de démarrage", "Échec de la connexion aux bases de données. L'application ne peut pas démarrer.")
            self.databases_connected = False
        else: 
            self.databases_connected = True

        self.current_user = None 
        self.selected_image_path = None

        self.setWindowTitle("Tawdrlik - App") 
        self.setWindowIcon(QIcon('icon.ico')) 
        self.setGeometry(100, 100, 950, 750) 
        self.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")

        # Widget principal et layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0) 

        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget, 1) 
        
        # Créer différentes pages
        self.setup_login_page()         # Index 0
        self.setup_register_page()      # Index 1
        self.setup_home_page()          # Index 2
        self.setup_post_item_page()     # Index 3
        self.setup_view_items_page()    # Index 4
        self.setup_profile_page()       # Index 5 

        # Label de message flash en bas
        self.flash_message_label = QLabel("")
        self.flash_message_label.setAlignment(Qt.AlignCenter)
        self.flash_message_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") 
        self.flash_message_label.setVisible(False) 
        self.flash_timer = QTimer(self) 
        self.flash_timer.setSingleShot(True)
        self.flash_timer.timeout.connect(lambda: self.flash_message_label.setVisible(False)) 

        self.main_layout.addWidget(self.flash_message_label) 

        self.stacked_widget.setCurrentIndex(0)

    def show_flash_message(self, message, duration=3000, is_error=False):
        """Afficher un message temporaire en bas."""
        if is_error:
            self.flash_message_label.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") # Style erreur
        else:
            self.flash_message_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") # Style succès 
        self.flash_message_label.setText(message) 
        self.flash_message_label.setVisible(True)
        self.flash_timer.start(duration)


    def setup_login_page(self):
        login_widget = QWidget()
        login_layout = QVBoxLayout(login_widget)
        login_layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel("Twadrlik") 
        title_label.setFont(QFont(FONT_FAMILY, 24, QFont.Bold))
        title_label.setStyleSheet(f"color: {ACCENT_COLOR};")
        title_label.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(title_label)

        subtitle_label = QLabel("Votre objet perdu a une place ici.")  
        subtitle_label.setFont(QFont(FONT_FAMILY, 14))
        subtitle_label.setStyleSheet(f"color: {PRIMARY_COLOR};")
        subtitle_label.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(subtitle_label)

        login_layout.addSpacing(40)

        form_container = QWidget()
        form_container.setStyleSheet("background-color: white; border-radius: 10px; padding: 20px; max-width: 400px;")
        form_container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        form_layout = QVBoxLayout(form_container)

        login_form = QFormLayout()
        login_form.setLabelAlignment(Qt.AlignLeft)
        login_form.setFormAlignment(Qt.AlignLeft)
        login_form.setSpacing(15)

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("Entrez votre email") 
        self.login_email.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        login_form.addRow("Email:", self.login_email)

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Entrez votre mot de passe") 
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        login_form.addRow("Mot de passe:", self.login_password) 

        form_layout.addLayout(login_form)
        form_layout.addSpacing(20)

        login_button = QPushButton("Se connecter") 
        login_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        login_button.clicked.connect(self.handle_login) 
        form_layout.addWidget(login_button)

        register_layout = QHBoxLayout()
        register_label = QLabel("Pas encore de compte ?") 
        register_button = QPushButton("S'inscrire") 
        register_button.setStyleSheet("background: none; border: none; color: #3BAFDA; text-decoration: underline; font-weight: bold;")
        register_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))

        register_layout.addWidget(register_label)
        register_layout.addWidget(register_button)
        register_layout.setAlignment(Qt.AlignCenter)
        form_layout.addLayout(register_layout)

        form_container_layout = QHBoxLayout()
        form_container_layout.addStretch()
        form_container_layout.addWidget(form_container)
        form_container_layout.addStretch()

        login_layout.addLayout(form_container_layout)
        login_layout.addStretch()

        self.stacked_widget.addWidget(login_widget)

    def setup_register_page(self):
        register_widget = QWidget()
        register_layout = QVBoxLayout(register_widget)
        register_layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel("Créer un compte") 
        title_label.setFont(QFont(FONT_FAMILY, 24, QFont.Bold))
        title_label.setStyleSheet(f"color: {ACCENT_COLOR};")
        title_label.setAlignment(Qt.AlignCenter)
        register_layout.addWidget(title_label)

        register_layout.addSpacing(20)

        form_container = QWidget()
        form_container.setStyleSheet("background-color: white; border-radius: 10px; padding: 20px; max-width: 400px;")
        form_layout = QVBoxLayout(form_container)

        register_form = QFormLayout()
        register_form.setLabelAlignment(Qt.AlignLeft)
        register_form.setFormAlignment(Qt.AlignLeft)
        register_form.setSpacing(15)

        self.register_username = QLineEdit()
        self.register_username.setPlaceholderText("Choisissez un nom d'utilisateur")
        self.register_username.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Nom d'utilisateur:", self.register_username) 

        self.register_email = QLineEdit()
        self.register_email.setPlaceholderText("Entrez votre email") 
        self.register_email.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Email:", self.register_email)

        self.register_password = QLineEdit()
        self.register_password.setPlaceholderText("Créez un mot de passe (min 6 car.)") 
        self.register_password.setEchoMode(QLineEdit.Password)
        self.register_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Mot de passe:", self.register_password)

        self.register_confirm_password = QLineEdit()
        self.register_confirm_password.setPlaceholderText("Confirmez votre mot de passe") 
        self.register_confirm_password.setEchoMode(QLineEdit.Password)
        self.register_confirm_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Confirmer Mot de passe:", self.register_confirm_password) 
        form_layout.addLayout(register_form)
        form_layout.addSpacing(20)

        register_button = QPushButton("S'inscrire") 
        register_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        register_button.clicked.connect(self.handle_register)
        form_layout.addWidget(register_button)

        login_layout = QHBoxLayout()
        login_label = QLabel("Déjà un compte ?") 
        login_button = QPushButton("Se connecter") 
        login_button.setStyleSheet("background: none; border: none; color: #3BAFDA; text-decoration: underline; font-weight: bold;")
        login_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))

        login_layout.addWidget(login_label)
        login_layout.addWidget(login_button)
        login_layout.setAlignment(Qt.AlignCenter)
        form_layout.addLayout(login_layout)

        form_container_layout = QHBoxLayout()
        form_container_layout.addStretch()
        form_container_layout.addWidget(form_container)
        form_container_layout.addStretch()

        register_layout.addLayout(form_container_layout)
        register_layout.addStretch()

        self.stacked_widget.addWidget(register_widget)

    def setup_home_page(self):
        home_widget = QWidget()
        home_layout = QVBoxLayout(home_widget)
        home_layout.setContentsMargins(10,10,10,10) 
        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 10px; padding: 15px 20px; margin-bottom: 15px;")
        header_layout = QHBoxLayout(header_container)

        self.welcome_label = QLabel("Bonjour !") 
        self.welcome_label.setFont(QFont(FONT_FAMILY, 15, QFont.Bold)) 
        self.welcome_label.setStyleSheet("color: white;")

        profile_button = QPushButton(QIcon.fromTheme("user-identity"), " Mon Profil & Réclamations") 
        profile_button.setStyleSheet("background-color: white; color: #3BAFDA; padding: 8px 15px; border-radius: 5px; font-weight: bold; border: none;")
        profile_button.setCursor(Qt.PointingHandCursor)
        profile_button.setIconSize(QSize(18, 18)) 
        profile_button.clicked.connect(self.show_profile_page) 

        logout_button = QPushButton(QIcon.fromTheme("application-exit"), " Déconnexion") 
        logout_button.setStyleSheet("background-color: #f44336; color: white; padding: 8px 15px; border-radius: 5px; font-weight: bold; border: none;")
        logout_button.setCursor(Qt.PointingHandCursor)
        logout_button.setIconSize(QSize(18, 18))
        logout_button.clicked.connect(self.handle_logout)

        header_layout.addWidget(self.welcome_label)
        header_layout.addStretch()
        header_layout.addWidget(profile_button)
        header_layout.addWidget(logout_button)

        home_layout.addWidget(header_container)

        # Contenu principal avec les boutons de fonctionnalités
        
        main_content = QWidget()
        main_content.setStyleSheet("background-color: white; border-radius: 10px; padding: 25px;")
        main_content_layout = QVBoxLayout(main_content)

        intro_label = QLabel("Que souhaitez-vous faire aujourd'hui ?")
        intro_label.setFont(QFont(FONT_FAMILY, 14))
        intro_label.setAlignment(Qt.AlignCenter) 
        intro_label.setStyleSheet(f"color: {ACCENT_COLOR}; margin-bottom: 20px;")

        main_content_layout.addWidget(intro_label)
        main_content_layout.addSpacing(20)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20) 

        button_style = """
            QPushButton {
                padding: 35px; 
                border-radius: 10px; 
                font-size: 15px; 
                font-weight: bold; 
                color: white;
            }
        """

        lost_item_button = QPushButton(QIcon.fromTheme("edit-find-replace"), "\nPublier un objet perdu") 
        lost_item_button.setStyleSheet(f"background-color: #ff9800; {button_style}")
        lost_item_button.setIconSize(QSize(48,48))
        lost_item_button.setCursor(Qt.PointingHandCursor)
        lost_item_button.clicked.connect(lambda: self.show_post_item_page("lost")) 

        found_item_button = QPushButton(QIcon.fromTheme("emblem-important"), "\nPublier un élément trouvé") 
        found_item_button.setStyleSheet(f"background-color: #4caf50; {button_style}")
        found_item_button.setIconSize(QSize(48,48))
        found_item_button.setCursor(Qt.PointingHandCursor)
        found_item_button.clicked.connect(lambda: self.show_post_item_page("found")) 

        view_items_button = QPushButton(QIcon.fromTheme("system-search"), "\nVoir tous les objets") 
        view_items_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; {button_style}")
        view_items_button.setIconSize(QSize(48,48))
        view_items_button.setCursor(Qt.PointingHandCursor)
        view_items_button.clicked.connect(self.show_view_items_page)

        buttons_layout.addWidget(lost_item_button)
        buttons_layout.addWidget(found_item_button)
        buttons_layout.addWidget(view_items_button)

        main_content_layout.addLayout(buttons_layout)
        home_layout.addWidget(main_content, 1) 

        self.stacked_widget.addWidget(home_widget)

    def setup_post_item_page(self):
        post_item_widget = QWidget()
        post_layout = QVBoxLayout(post_item_widget)
        post_layout.setContentsMargins(20, 20, 20, 20)

        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px; margin-bottom: 25px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        self.post_title_label = QLabel("Publier un objet") 
        self.post_title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        self.post_title_label.setStyleSheet("color: white;")

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Retour à l'accueil") 
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; }")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setIconSize(back_button.sizeHint() * 0.6) 
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2)) 

        header_layout.addWidget(self.post_title_label)
        header_layout.addStretch()
        header_layout.addWidget(back_button)

        post_layout.addWidget(header_container)

        form_container = QWidget()
        form_container.setStyleSheet("background-color: white; border-radius: 8px; padding: 30px; border: 1px solid #e0e0e0;")
        form_layout = QVBoxLayout(form_container)

        post_form = QFormLayout()
        post_form.setLabelAlignment(Qt.AlignLeft)
        post_form.setFormAlignment(Qt.AlignLeft)
        post_form.setSpacing(18)
        post_form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        field_style = "padding: 12px; border-radius: 5px; font-size: 14px;"

        self.item_title = QLineEdit()
        self.item_title.setPlaceholderText("ex: Portefeuille noir, iPhone 13") 
        self.item_title.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Titre :</b>*"), self.item_title) 

        self.item_category = QComboBox() 
        self.item_category.addItems(["Électronique", "Vêtements", "Documents", "Clés","Bijoux", "Livres", "Portefeuilles","Sacs à main", "Autre"])
        self.item_category.setStyleSheet(field_style + " padding-right: 15px;")
        post_form.addRow(QLabel("<b>Catégorie :</b>"), self.item_category)

        self.item_location = QLineEdit()
        self.item_location.setPlaceholderText("ex: Rue Mohamed v beni Mellal , Centre de Goulmima ") 
        self.item_location.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Lieu :</b>*"), self.item_location) 

        self.item_date = QDateEdit()
        self.item_date.setDate(QDate.currentDate())
        self.item_date.setCalendarPopup(True) 
        self.item_date.setDisplayFormat("yyyy-MM-dd")
        self.item_date.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Date Perdu/Trouvé :</b>"), self.item_date) 

        self.item_description = QTextEdit()
        self.item_description.setPlaceholderText("Fournissez des détails : couleur, marque, signes distinctifs, contenu...") 
        self.item_description.setStyleSheet(field_style)
        self.item_description.setMinimumHeight(100)
        post_form.addRow(QLabel("<b>Description :</b>*"), self.item_description) 

        image_layout = QHBoxLayout()
        self.select_image_button = QPushButton(QIcon.fromTheme("insert-image"), " Sélectionner une image...")
        self.select_image_button.setStyleSheet(f"QPushButton {{ background-color: #e0e0e0; color: #333; padding: 10px 15px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; }} QPushButton:hover {{ background-color: #d5d5d5; }}")
        self.select_image_button.setCursor(Qt.PointingHandCursor)
        self.select_image_button.clicked.connect(self.select_image_file)

        self.image_preview_label = QLabel() 
        self.image_preview_label.setFixedSize(100, 100) 
        self.image_preview_label.setAlignment(Qt.AlignCenter)
        self.image_preview_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 4px;")
        self.image_preview_label.setText("Aucune image\nSélectionnée") 
        self.image_preview_label.setToolTip("Aperçu de l'image") 


        image_layout.addWidget(self.select_image_button)
        image_layout.addWidget(self.image_preview_label)
        image_layout.addStretch()

        post_form.addRow(QLabel("<b>Image :</b>"), image_layout) 

        form_layout.addLayout(post_form)
        form_layout.addSpacing(30)

        self.submit_item_button = QPushButton("Soumettre l'objet") 
        self.submit_item_button.setStyleSheet(f"background-color: {ACCENT_COLOR}; color: white; padding: 14px; border-radius: 5px; font-weight: bold; font-size: 16px; border: none;")
        self.submit_item_button.setCursor(Qt.PointingHandCursor)
        self.submit_item_button.clicked.connect(self.handle_post_item)
        form_layout.addWidget(self.submit_item_button)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none; background-color: white;")
        scroll_area.setWidget(form_container)

        post_layout.addWidget(scroll_area)

        self.stacked_widget.addWidget(post_item_widget)
        self.current_item_status = "lost" 
        
    def select_image_file(self):
        """Ouvrir une boîte de dialogue pour sélectionner une image à poster."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Sélectionner l'image de l'objet", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.gif)", options=options)
        if file_path:
            try:
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    raise ValueError("Fichier image invalide")

                with open(file_path, 'rb') as f:
                     image_data_temp = f.read()
                     if len(image_data_temp) > 16 * 1024 * 1024: # 16 Mo max
                          QMessageBox.warning(self, "Image trop grande", "L'image de l'objet doit faire moins de 16 Mo.")

                self.selected_image_path = file_path
                preview_pixmap = pixmap.scaled(self.image_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_preview_label.setPixmap(preview_pixmap)
                self.image_preview_label.setToolTip(file_path) 

            except Exception as e:
                 QMessageBox.warning(self, "Erreur d'image", f"Impossible de charger l'image : {e}") 
                 self.selected_image_path = None
                 self.image_preview_label.clear()
                 self.image_preview_label.setText("Erreur")
                 self.image_preview_label.setToolTip("Erreur chargement image") 


    def setup_view_items_page(self):
        view_items_widget = QWidget()
        view_layout = QVBoxLayout(view_items_widget)
        view_layout.setContentsMargins(20, 20, 20, 20)

        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px; margin-bottom: 20px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        title_label = QLabel("Parcourir les objets") 
        title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        title_label.setStyleSheet("color: white;")

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Retour à l'accueil") 
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } ")
        back_button.setCursor(Qt.PointingHandCursor) 
        back_button.setIconSize(back_button.sizeHint() * 0.6)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(back_button)

        view_layout.addWidget(header_container)

        # Section Filtre
        filter_container = QWidget()
        filter_container.setStyleSheet("background-color: white; border-radius: 8px; padding: 18px 25px; margin-bottom: 20px; border: 1px solid #e0e0e0;")
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setSpacing(15)

        filter_label = QLabel("Filtrer par :") 
        filter_label.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        filter_label.setStyleSheet(f"color: {ACCENT_COLOR};border:None")

        combo_style = "QComboBox { padding: 10px; min-width: 180px; font-size: 14px; background-color: white; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background-color: white; selection-background-color: #e0f7ff; selection-color: black; }"

        self.category_filter = QComboBox()
        self.category_filter.addItem("Toutes les catégories") 
        self.category_filter.setStyleSheet(combo_style)
        self.category_filter.setCursor(Qt.PointingHandCursor)

        self.location_filter = QComboBox()
        self.location_filter.addItem("Tous les lieux") 
        self.location_filter.setStyleSheet(combo_style)
        self.location_filter.setCursor(Qt.PointingHandCursor)

        apply_filter_button = QPushButton(QIcon.fromTheme("edit-find"), " Appliquer le filtre") 
        apply_filter_button.setStyleSheet(f"QPushButton {{ background-color: {ACCENT_COLOR}; color: white; padding: 10px 20px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; }} QPushButton:hover {{ background-color: #162d40; }}")
        apply_filter_button.setCursor(Qt.PointingHandCursor)
        apply_filter_button.setIconSize(apply_filter_button.sizeHint() * 0.6)
        apply_filter_button.clicked.connect(self.apply_item_filters) 

        reset_filter_button = QPushButton(QIcon.fromTheme("edit-clear"), " Réinitialiser") 
        reset_filter_button.setStyleSheet("QPushButton { background-color: #e0e0e0; color: #333; padding: 10px 20px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } QPushButton:hover { background-color: #d5d5d5; }")
        reset_filter_button.setCursor(Qt.PointingHandCursor)
        reset_filter_button.setIconSize(reset_filter_button.sizeHint() * 0.6)
        reset_filter_button.clicked.connect(self.reset_item_filters) 

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(QLabel("Catégorie :")) 
        filter_layout.addWidget(self.category_filter)
        filter_layout.addWidget(QLabel("Lieu :")) 
        filter_layout.addWidget(self.location_filter)
        filter_layout.addSpacing(10)
        filter_layout.addWidget(apply_filter_button)
        filter_layout.addWidget(reset_filter_button)
        filter_layout.addStretch()

        view_layout.addWidget(filter_container)

        # Zone de liste des objets (Scrollable)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none; background-color: transparent;")

        scroll_content = QWidget() 
        self.items_list_layout = QVBoxLayout(scroll_content)
        self.items_list_layout.setAlignment(Qt.AlignTop)
        self.items_list_layout.setSpacing(18)
        self.items_list_layout.setContentsMargins(5, 5, 10, 5)

        scroll_area.setWidget(scroll_content)
        view_layout.addWidget(scroll_area)

        self.stacked_widget.addWidget(view_items_widget)


    def setup_profile_page(self):
        
        """Configurer la page de profil, incluant les sections pour les objets de l'utilisateur et les réclamations."""
        
        profile_widget = QWidget()
        profile_layout = QVBoxLayout(profile_widget)
        profile_layout.setContentsMargins(20, 20, 20, 20)
        profile_layout.setSpacing(20) 

        # En-tête
        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        title_label = QLabel("Mon Profil & Gestion des Réclamations") 
        title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        title_label.setStyleSheet("color: white;") 

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Retour à l'accueil") 
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } ")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setIconSize(back_button.sizeHint() * 0.6)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(back_button)
        profile_layout.addWidget(header_container)

        # --- Section Informations Utilisateur ---
        
        user_info_group = QGroupBox("Informations Utilisateur") 
        user_info_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        user_info_container_layout = QVBoxLayout(user_info_group) 

        user_info_container_layout.setSpacing(8)
        self.profile_username_label = QLabel("Nom d'utilisateur : Chargement...") 
        self.profile_username_label.setFont(QFont(FONT_FAMILY, 14))
        self.profile_email_label = QLabel("Email : Chargement...") 
        self.profile_email_label.setFont(QFont(FONT_FAMILY, 14))
        user_info_container_layout.addWidget(self.profile_username_label)
        user_info_container_layout.addWidget(self.profile_email_label)
        profile_layout.addWidget(user_info_group)


        # --- Séparateur pour Mes Objets et Réclamations ---
        
        splitter = QWidget() 
        splitter_layout = QHBoxLayout(splitter)
        splitter_layout.setSpacing(20)
        profile_layout.addWidget(splitter, 1) # Rendre cette section extensible


        # --- Côté Gauche : Mes articles publiés ---
        my_items_group = QGroupBox("Mes articles publiés")
        my_items_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        my_items_layout = QVBoxLayout(my_items_group)

        items_scroll_area = QScrollArea()
        items_scroll_area.setWidgetResizable(True)
        items_scroll_area.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: white;")
        items_scroll_content = QWidget()
        self.user_items_layout = QVBoxLayout(items_scroll_content) 
        self.user_items_layout.setAlignment(Qt.AlignTop)
        self.user_items_layout.setSpacing(15)
        self.user_items_layout.setContentsMargins(10, 10, 10, 10)
        items_scroll_area.setWidget(items_scroll_content)
        my_items_layout.addWidget(items_scroll_area)
        splitter_layout.addWidget(my_items_group)


        # --- Côté Droit : Gestion des Réclamations ---
        
        claims_management_group = QGroupBox("Gestion des Réclamations") 
        claims_management_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        claims_management_layout = QVBoxLayout(claims_management_group)
        claims_management_layout.setSpacing(15)

        # Réclamations sur Mes Objets (pour les Propriétaires)
        
        claims_on_my_items_group = QGroupBox("Réclamations Reçues sur Mes Objets") 
        claims_on_my_items_layout_outer = QVBoxLayout(claims_on_my_items_group)
        claims_on_items_scroll = QScrollArea()
        claims_on_items_scroll.setWidgetResizable(True)
        claims_on_items_scroll.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: #f8f8f8;") 
        claims_on_items_content = QWidget()
        self.claims_on_my_items_layout = QVBoxLayout(claims_on_items_content) 
        self.claims_on_my_items_layout.setAlignment(Qt.AlignTop)
        self.claims_on_my_items_layout.setSpacing(10) 
        self.claims_on_my_items_layout.setContentsMargins(8, 8, 8, 8) 
        claims_on_items_scroll.setWidget(claims_on_items_content)
        claims_on_my_items_layout_outer.addWidget(claims_on_items_scroll)
        claims_management_layout.addWidget(claims_on_my_items_group, 1) 

        # Mes Réclamations Soumises (pour les Réclamants)
        
        my_submitted_claims_group = QGroupBox("Mes Réclamations Soumises")
        my_submitted_claims_layout_outer = QVBoxLayout(my_submitted_claims_group)
        my_claims_scroll = QScrollArea()
        my_claims_scroll.setWidgetResizable(True)
        my_claims_scroll.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: #f8f8f8;")
        my_claims_content = QWidget()
        self.my_claims_layout = QVBoxLayout(my_claims_content) 
        self.my_claims_layout.setAlignment(Qt.AlignTop)
        self.my_claims_layout.setSpacing(10)
        self.my_claims_layout.setContentsMargins(8, 8, 8, 8)
        my_claims_scroll.setWidget(my_claims_content)
        my_submitted_claims_layout_outer.addWidget(my_claims_scroll)
        claims_management_layout.addWidget(my_submitted_claims_group, 1) 

        splitter_layout.addWidget(claims_management_group)


        self.stacked_widget.addWidget(profile_widget)


    # --- Méthodes de gestion d'événements ---
    
    def handle_login(self):
        """Gérer la connexion de l'utilisateur"""
        if not self.databases_connected: 
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de se connecter.", is_error=True) 
             return

        email = self.login_email.text().strip()
        password = self.login_password.text().strip() 

        if not email or not password:
            QMessageBox.warning(self, "Échec de la connexion", "Veuillez entrer l'email et le mot de passe.") 
            return
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            QMessageBox.warning(self, "Échec de la connexion", "Veuillez entrer une adresse email valide.")

        success, result = login_user(email, password)

        if success:
            self.current_user = result 
            self.welcome_label.setText(f"Bonjour, <b>{self.current_user['nom_utilisateur']}</b> !")
            self.stacked_widget.setCurrentIndex(2)  
            self.login_email.clear() 
            self.login_password.clear()
            self.show_flash_message(f"Connecté en tant que {self.current_user['nom_utilisateur']}.") 
        else:
            QMessageBox.warning(self, "Échec de la connexion", str(result)) 
            self.current_user = None


    def handle_register(self):
        """Gérer l'inscription de l'utilisateur"""
        if not self.databases_connected:
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de s'inscrire.", is_error=True) 
             return

        username = self.register_username.text().strip()
        email = self.register_email.text().strip()
        password = self.register_password.text().strip()
        confirm_password = self.register_confirm_password.text().strip()

        if not username or not email or not password or not confirm_password:
            QMessageBox.warning(self, "Échec de l'inscription", "Veuillez remplir tous les champs.") 
            return
        if password != confirm_password:
            QMessageBox.warning(self, "Échec de l'inscription", "Les mots de passe ne correspondent pas.") 
            return
        if len(password) < 6:
            QMessageBox.warning(self, "Échec de l'inscription", "Le mot de passe doit comporter au moins 6 caractères.") 
            return
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            QMessageBox.warning(self, "Échec de l'inscription", "Veuillez entrer une adresse email valide.") 
            return

        success, message = register_user(username, email, password)

        if success:
            QMessageBox.information(self, "Inscription réussie",
                                   "Compte créé ! Vous pouvez maintenant vous connecter.")
            self.stacked_widget.setCurrentIndex(0)  # Retour à la page de connexion
            self.register_username.clear()
            self.register_email.clear()
            self.register_password.clear()
            self.register_confirm_password.clear()
        else:
            QMessageBox.warning(self, "Échec de l'inscription", message)

   
    def handle_logout(self):
        """Gérer la déconnexion de l'utilisateur"""
        reply = QMessageBox.question(self, 'Confirmer la déconnexion', 'Êtes-vous sûr de vouloir vous déconnecter ?', 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logged_out_user = self.current_user['nom_utilisateur'] if self.current_user else "Utilisateur" 
            self.current_user = None
            self.stacked_widget.setCurrentIndex(0) 
            # Effacer les champs sensibles
            self.login_email.clear()
            self.login_password.clear()
            self.item_title.clear() 
            self.item_location.clear() 
            self.item_description.clear()
            self.image_preview_label.clear()  
            self.selected_image_path = None
            self.profile_username_label.setText("Nom d'utilisateur : ")
            self.profile_email_label.setText("Email : ") 
            self.clear_layout(self.user_items_layout)
            self.clear_layout(self.claims_on_my_items_layout)
            self.clear_layout(self.my_claims_layout) 
            self.show_flash_message(f"{logged_out_user} déconnecté avec succès.")


    def show_post_item_page(self, status):
        """Afficher la page de signalement d'objet avec le statut spécifié (perdu/trouvé)"""
        if not self.current_user:
             self.show_flash_message("Veuillez vous connecter pour publier des objets.", is_error=True) 
             self.stacked_widget.setCurrentIndex(0) 
             return

        self.current_item_status = status 
        button_style_base = """QPushButton { color: white;padding: 14px; border-radius: 5px; font-weight: bold;  font-size: 16px; border: none; }"""
        
        if status == "lost":
            self.post_title_label.setText("Publier un objet perdu") 
            self.submit_item_button.setStyleSheet(button_style_base + "QPushButton { background-color: #ffb74d; }") 
            self.item_date.setToolTip("Date à laquelle l'objet a été perdu") 
        else: # Found
            self.post_title_label.setText("Publier un objet trouvé") 
            self.submit_item_button.setStyleSheet(button_style_base + "QPushButton { background-color: #81c784; }") 
            self.item_date.setToolTip("Date à laquelle l'objet a été trouvé") 

        # Effacer les champs du formulaire
        self.item_title.clear()
        self.item_category.setCurrentIndex(0) 
        self.item_location.clear()
        self.item_date.setDate(QDate.currentDate()) 
        self.item_description.clear()
        self.selected_image_path = None
        self.image_preview_label.clear(); 
        self.image_preview_label.setText("Aucune image\nSélectionnée") 

        self.stacked_widget.setCurrentIndex(3)


    def handle_post_item(self):
        """Gérer le Publication d'un nouvel objet, y compris l'image"""
        
        if not self.current_user:
            self.show_flash_message("Vous devez être connecté pour signaler un objet.", is_error=True) 
            return
        if not self.databases_connected:
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de signaler l'objet.", is_error=True) 
             return

        title = self.item_title.text().strip()
        category = self.item_category.currentText()
        location = self.item_location.text().strip()
        date = self.item_date.date().toString("yyyy-MM-dd")
        description = self.item_description.toPlainText().strip()

        if not title or not location or not description:
            QMessageBox.warning(self, "Erreur de soumission", "Veuillez remplir Titre, Lieu et Description.") 
            return
        # Garder l'image obligatoire
        if not self.selected_image_path:
            QMessageBox.warning(self, "Erreur de soumission", "Veuillez sélectionner une image pour l'objet.") 
            return

        # Lire les données de l'image
        image_data = None 
        try:
            with open(self.selected_image_path, 'rb') as f:
                image_data = f.read()
            if len(image_data) > 16 * 1024 * 1024: # 16 Mo max
                 QMessageBox.warning(self, "Erreur d'image", "L'image sélectionnée est trop grande (max 16 Mo).")
                 return
        except Exception as e:
            QMessageBox.warning(self, "Erreur d'image", f"Impossible de lire le fichier image : {e}")
            return 

        # Sauvegarder l'objet
        success, message = save_item( 
            self.current_user['id_utilisateur'], title, category, location, date,
            self.current_item_status, description, image_data 
        )

        if success:
            self.show_flash_message(message) 
            self.show_view_items_page() 
        else:
            QMessageBox.critical(self, "Erreur lors de la sauvegarde de l'objet", message) 


    def show_view_items_page(self):
        """Afficher la page avec tous les objets non récupérés, en rafraîchissant les filtres"""
        if not self.current_user:
             self.show_flash_message("Veuillez vous connecter pour voir les objets.", is_error=True) 
             self.stacked_widget.setCurrentIndex(0)
             return
        if not self.databases_connected:
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de charger les objets.", is_error=True) 
             pass

        # Mettre à jour les combobox de filtre
        current_cat = self.category_filter.currentText()
        current_loc = self.location_filter.currentText()
        self.category_filter.clear() 
        self.category_filter.addItems(get_unique_categories()) 
        cat_index = self.category_filter.findText(current_cat)
        self.category_filter.setCurrentIndex(cat_index if cat_index != -1 else 0)
        self.location_filter.clear()
        self.location_filter.addItems(get_unique_locations()) 
        loc_index = self.location_filter.findText(current_loc)
        self.location_filter.setCurrentIndex(loc_index if loc_index != -1 else 0)

        self.stacked_widget.setCurrentIndex(4)
        self.load_all_items(
             self.category_filter.currentText(),
             self.location_filter.currentText(),
             include_recovered=False 
        )


    def apply_item_filters(self):
        """Appliquer les filtres à la liste des objets"""
        if not self.current_user: return
        self.load_all_items(
            self.category_filter.currentText(),
            self.location_filter.currentText(),
            include_recovered=False  
        )

    def reset_item_filters(self):
        """Réinitialiser les filtres par défaut et recharger les objets"""
        if not self.current_user: return
        self.category_filter.setCurrentIndex(0) 
        self.location_filter.setCurrentIndex(0)
        self.load_all_items(include_recovered=False)  


    def load_all_items(self, filter_category=None, filter_location=None, include_recovered=False):
        
        """Charger et afficher les objets avec filtrage et statut de récupération optionnels"""
        
        if not self.databases_connected: return 
        self.clear_layout(self.items_list_layout)

        loading_label = QLabel("Chargement des objets...") 
        loading_label.setAlignment(Qt.AlignCenter); 
        loading_label.setStyleSheet("color: #888; margin: 30px 0;")
        self.items_list_layout.addWidget(loading_label)
        QApplication.processEvents() 

        
        cat_to_send = filter_category if filter_category != "Toutes les catégories" else None
        loc_to_send = filter_location if filter_location != "Tous les lieux" else None

        items = get_all_items(cat_to_send, loc_to_send, include_recovered) 
        self.clear_layout(self.items_list_layout)            

        if not items:
            no_items_label = QLabel("Aucun objet trouvé correspondant à vos critères.") 
            no_items_label.setAlignment(Qt.AlignCenter);
            no_items_label.setStyleSheet("color: #666; margin: 30px 0;")
            self.items_list_layout.addWidget(no_items_label)
            return 

        for item in items:
            item_widget = self.create_item_widget(item, context='view_all')
            self.items_list_layout.addWidget(item_widget) 


    def show_profile_page(self):
        """Afficher la page de profil utilisateur, incluant les objets et les sections de réclamations"""
        if not self.current_user:
            self.show_flash_message("Veuillez vous connecter pour voir votre profil.", is_error=True) 
            self.stacked_widget.setCurrentIndex(0)
            return
        if not self.databases_connected:
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de charger les données du profil.", is_error=True)
             pass

        # Mettre à jour l'affichage des informations utilisateur
        self.profile_username_label.setText(f"Nom d'utilisateur : <b>{self.current_user['nom_utilisateur']}</b>") 
        self.profile_email_label.setText(f"Email : {self.current_user['email']}") 

        self.stacked_widget.setCurrentIndex(5) 

        # Charger les objets de l'utilisateur et les réclamations (reçues et soumises)
        self.load_user_items() 
        self.load_claims_on_my_items()
        self.load_my_submitted_claims()

    def load_user_items(self):
        """Charger les objets signalés par l'utilisateur actuel pour la page de profil"""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.user_items_layout)

        loading_label = QLabel("Chargement de vos objets..."); 
        loading_label.setAlignment(Qt.AlignCenter); 
        loading_label.setStyleSheet("color: #888; margin: 20px 0;") 
        self.user_items_layout.addWidget(loading_label)
        QApplication.processEvents()

        items = get_user_items(self.current_user['id_utilisateur'])
        self.clear_layout(self.user_items_layout)

        if not items:
            no_items_label = QLabel("Vous n'avez pas encore signalé d'objets."); no_items_label.setAlignment(Qt.AlignCenter); no_items_label.setStyleSheet("color: #666; margin: 20px 0;")
            self.user_items_layout.addWidget(no_items_label)
            return 

        for item in items:
            item_widget = self.create_item_widget(item, context='profile_own')
            self.user_items_layout.addWidget(item_widget)


    def load_claims_on_my_items(self):
        """Charger les réclamations faites par d'autres sur les objets appartenant à l'utilisateur actuel."""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.claims_on_my_items_layout)

        loading_label = QLabel("Chargement des réclamations reçues..."); loading_label.setAlignment(Qt.AlignCenter); loading_label.setStyleSheet("color: #888; margin: 15px 0;") # "Loading received claims..." -> "Chargement des réclamations reçues..."
        self.claims_on_my_items_layout.addWidget(loading_label)
        QApplication.processEvents()

        # Besoin d'obtenir d'abord les objets appartenant à l'utilisateur, puis obtenir les réclamations pour chaque objet
        
        my_items = get_user_items(self.current_user['id_utilisateur']) 
        
        all_claims_on_my_items = []
        for item in my_items:
            # Afficher uniquement les réclamations pour les objets qui ne sont PAS encore récupérés
            if item.get('status') != 'recovered':
                claims_for_this_item = get_claims_for_item(item['id_objet'])
                for claim in claims_for_this_item:
                    claim['item_title'] = item['titre'] 
                    all_claims_on_my_items.append(claim) 

        # Trier les réclamations (par ex., par date, ou grouper par objet) - tri simple par date pour l'instant
        all_claims_on_my_items.sort(key=lambda x: x['claim_created_at'], reverse=True)

        self.clear_layout(self.claims_on_my_items_layout) 

        if not all_claims_on_my_items:
            no_claims_label = QLabel("Aucune réclamation en attente sur vos objets.") 
            no_claims_label.setAlignment(Qt.AlignCenter)
            no_claims_label.setStyleSheet("color: #666; margin: 15px 0;") 
            self.claims_on_my_items_layout.addWidget(no_claims_label)
            return

        for claim in all_claims_on_my_items:
            claim_widget = self.create_claim_widget(claim, context='owner_view')
            self.claims_on_my_items_layout.addWidget(claim_widget)


    def load_my_submitted_claims(self):
        """Charger les réclamations soumises par l'utilisateur actuel."""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.my_claims_layout)

        loading_label = QLabel("Chargement de vos réclamations soumises...");
        loading_label.setAlignment(Qt.AlignCenter); 
        loading_label.setStyleSheet("color: #888; margin: 15px 0;") 
        self.my_claims_layout.addWidget(loading_label)
        QApplication.processEvents()

        my_claims = get_claims_by_claimant(self.current_user['id_utilisateur'])
        self.clear_layout(self.my_claims_layout)

        if not my_claims:
            no_claims_label = QLabel("Vous n'avez pas encore soumis de réclamations.");
            no_claims_label.setAlignment(Qt.AlignCenter);
            no_claims_label.setStyleSheet("color: #666; margin: 15px 0;") 
            self.my_claims_layout.addWidget(no_claims_label)
            return

        for claim in my_claims:
            claim_widget = self.create_claim_widget(claim, context='claimant_view')
            self.my_claims_layout.addWidget(claim_widget)


    def create_item_widget(self, item_data, context='view_all'):
        
        """Crée un widget pour afficher un objet.Contexte peut être 'view_all', 'profile_own'.Inclut l'image, les détails et les boutons spécifiques au contexte.Attend un dictionnaire item_data."""
        
        item_widget = QWidget()
        item_widget.setStyleSheet("background-color: #ffffff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 0px;")

        card_layout = QHBoxLayout(item_widget)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)

        # --- Zone Image ---
        
        image_label = QLabel()
        img_size = 100  
        image_label.setFixedSize(img_size, img_size)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setStyleSheet("background-color: #f0f0f0; border-radius: 5px; border: 1px solid #ddd;")

        pixmap = self.load_pixmap_from_data(item_data.get('image_data')) 
        if pixmap:
            scaled_pixmap = pixmap.scaled(image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            image_label.setToolTip("Image de l'objet") 
        else:
            image_label.setText("Pas d'image") 
            image_label.setToolTip("Aucune image fournie")

        card_layout.addWidget(image_label, 0)

        # --- Zone Détails ---
        
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(5) 

        # Ligne supérieure : Titre et Statut
        
        top_line_layout = QHBoxLayout()
        title_text = item_data.get('titre', 'Sans Titre') 
        title_label = QLabel(f"<b>{title_text}</b>")
        title_label.setStyleSheet(f"color: {ACCENT_COLOR}; font-size: 14px;")
        title_label.setWordWrap(True) 
        title_label.setToolTip(title_text)

        item_status = item_data.get('statut_objet','unknown') 
        
        # Traduire les statuts pour l'affichage
        
        status_display = {'lost': 'PERDU', 'found': 'TROUVÉ', 'recovered': 'RÉCUPÉRÉ', 'unknown': 'INCONNU'}
        status_label = QLabel(status_display.get(item_status, item_status.lower()))
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter) 
        status_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        status_style = "color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;"
        if item_status == 'lost': status_label.setStyleSheet(f"background-color: #ffb74d; {status_style}") # Orange pour perdu
        elif item_status == 'found': status_label.setStyleSheet(f"background-color: #81c784; {status_style}") # Vert pour trouvé
        elif item_status == 'recovered': status_label.setStyleSheet(f"background-color: #78909c; {status_style}") # Gris pour récupéré
        else: status_label.setStyleSheet(f"background-color: #bdbdbd; {status_style}") # Gris clair pour inconnu


        top_line_layout.addWidget(title_label)
        top_line_layout.addStretch() 
        top_line_layout.addWidget(status_label)
        details_layout.addLayout(top_line_layout)

        # Section du milieu : Autres détails
        details_form = QFormLayout()
        details_form.setContentsMargins(0, 5, 0, 0)
        details_form.setSpacing(4)
        details_form.setLabelAlignment(Qt.AlignLeft)
        details_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    
        def create_detail_label(text):
            lbl = QLabel(str(text)) 
            lbl.setStyleSheet("font-size: 12px; color: #444;")
            lbl.setWordWrap(True)
            return lbl

        # Afficher le propriétaire seulement si pas sur la page de profil propre 
        
        if context != 'profile_own' and 'proprietaire_nom_utilisateur' in item_data:
            details_form.addRow(QLabel("<b>Publier par :</b>"), create_detail_label(item_data['proprietaire_nom_utilisateur'])) 
        details_form.addRow(QLabel("<b>Catégorie :</b>"), create_detail_label(item_data.get('categorie', 'N/A'))) 
        details_form.addRow(QLabel("<b>Lieu :</b>"), create_detail_label(item_data.get('lieu', 'N/A'))) 
        details_form.addRow(QLabel("<b>Date :</b>"), create_detail_label(item_data.get('date_evenement', 'N/A'))) 
        details_layout.addLayout(details_form)

        # Description
        desc_text = item_data.get('description', 'Aucune description.') 
        description_label = QLabel(desc_text)
        description_label.setWordWrap(True)
        description_label.setStyleSheet("font-size: 12px; color: #555; margin-top: 5px;")
        description_label.setAlignment(Qt.AlignTop)
        details_layout.addWidget(description_label, 1) 

        # --- Zone Bouton d'Action ---
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 8, 0, 0) 
        button_layout.addStretch() 

        # --- *** CONDITION MISE À JOUR POUR LE BOUTON RÉCLAMER *** ---
        
        # Vérifier si l'utilisateur est connecté avant de vérifier l'ID
        
        user_logged_in = self.current_user is not None
        current_user_id = self.current_user['id_utilisateur'] if user_logged_in else -1 # Utiliser -1 si non connecté

        is_claimable = ( user_logged_in and 
                         context == 'view_all' and                         # Doit être sur la page de vue générale
                         item_data.get('statut_objet') in ['found', 'lost'] and  # * AUTORISER LA RÉCLAMATION D'OBJETS 'trouvés' OU 'perdus' *
                         item_data.get('id_utilisateur_proprietaire') != current_user_id )     # Ne peut pas réclamer son propre objet 

        if is_claimable:
            claim_button = QPushButton(QIcon.fromTheme("mail-mark-unread"), " Réclamer cet objet")
            claim_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 6px 12px; border-radius: 4px; font-size: 12px; font-weight: bold; border:none;")
            claim_button.setCursor(Qt.PointingHandCursor) 
            claim_button.clicked.connect(lambda checked, iid=item_data['id_objet']: self.handle_claim_button_click(iid))
            button_layout.addWidget(claim_button) 

        if button_layout.count() > 1: 
            details_layout.addLayout(button_layout)
        else:
            details_layout.addSpacerItem(QSpacerItem(0, 10, QSizePolicy.Minimum, QSizePolicy.Expanding)) 


        card_layout.addWidget(details_widget, 1) 
        return item_widget


    def create_claim_widget(self, claim_data, context='owner_view'):
        """Crée un widget pour afficher une réclamation.
           Contexte : 'owner_view' (vue propriétaire) ou 'claimant_view' (vue réclamant).
           Inclut les détails de la réclamation, l'aperçu des preuves et les boutons spécifiques au contexte.
           Attend un dictionnaire claim_data.
        """
        claim_widget = QWidget()
        base_style = "border-radius: 6px; border: 1px solid #ccc; padding: 10px;"
        claim_status = claim_data.get('claim_status', 'pending')
        bg_color = "#ffffff" 
        if claim_status == 'accepted': 
            bg_color = "#e8f5e9" 
        elif claim_status == 'rejected': 
            bg_color = "#ffebee" 

        claim_widget.setStyleSheet(f"background-color: {bg_color}; {base_style}")

        main_layout = QVBoxLayout(claim_widget)
        main_layout.setSpacing(8)

        top_line_layout = QHBoxLayout() 
        top_line_layout.setContentsMargins(0,0,0,0)

        info_label = QLabel()
        info_label.setStyleSheet("font-size: 13px;")
        info_label.setWordWrap(True)
        # Traduire les textes
        if context == 'claimant_view':
             item_title = claim_data.get('item_title', 'Objet inconnu') 
             item_status_for_claim = claim_data.get('item_status', '?')
             status_display_item = {'lost': 'PERDU', 'found': 'TROUVÉ', 'recovered': 'RÉCUPÉRÉ', '?':'?'} 
             info_label.setText(f"Votre réclamation sur : <b>{item_title}</b> (Statut objet : {status_display_item.get(item_status_for_claim, item_status_for_claim.upper())})") 
             info_label.setToolTip(f"Réclamation sur l'objet ID : {claim_data.get('id_objet_reclame')}") 
        else: # owner_view
             claimant_name = claim_data.get('claimant_username', 'Utilisateur inconnu') 
             item_title_for_owner = claim_data.get('item_title', 'Votre Objet') 
             info_label.setText(f"Réclamation par <b>{claimant_name}</b> sur : <i>{item_title_for_owner}</i>")
             info_label.setToolTip(f"ID Réclamation : {claim_data.get('claim_id')}, ID Réclamant : {claim_data.get('id_utilisateur_reclamant')}")


        # Traduire les statuts de réclamation pour l'affichage
        status_display_claim = {'pending': 'EN ATTENTE', 'accepted': 'ACCEPTÉE', 'rejected': 'REJETÉE'}
        status_label = QLabel(status_display_claim.get(claim_status, claim_status.upper()))
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        status_style = "color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;"
        if claim_status == 'pending': status_label.setStyleSheet(f"background-color: #ffc107; {status_style}") 
        elif claim_status == 'accepted': status_label.setStyleSheet(f"background-color: #4caf50; {status_style}") 
        elif claim_status == 'rejected': status_label.setStyleSheet(f"background-color: #f44336; {status_style}") 
        else: status_label.setStyleSheet(f"background-color: #bdbdbd; {status_style}") 
        
        top_line_layout.addWidget(info_label, 1) 
        top_line_layout.addWidget(status_label)
        main_layout.addLayout(top_line_layout)

        # Raison de la réclamation
        reason_label = QLabel(f"<b>Raison :</b> {claim_data.get('motif_reclamation', 'Aucune raison fournie.')}") 
        reason_label.setStyleSheet("font-size: 12px; color: #333;") 
        reason_label.setWordWrap(True)
        main_layout.addWidget(reason_label) 

        # Date de la réclamation
        created_at_raw = claim_data.get('claim_created_at', '')
        created_at_str = str(created_at_raw).split('.')[0] if created_at_raw else 'Date inconnue' 
        date_label = QLabel(f"<i>Soumis le : {created_at_str}</i>") 
        date_label.setStyleSheet("font-size: 11px; color: #666;") 
        main_layout.addWidget(date_label)


        # Image de preuve 
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 5, 0, 0)

        evidence_data = claim_data.get('evidence_image_data')
        if evidence_data:
             evidence_img_label = QLabel()
             evidence_img_size = 60
             evidence_img_label.setFixedSize(evidence_img_size, evidence_img_size)
             evidence_img_label.setAlignment(Qt.AlignCenter)
             evidence_img_label.setStyleSheet("background-color: #e0e0e0; border-radius: 4px; border: 1px solid #bbb;")
             pixmap = self.load_pixmap_from_data(evidence_data)
             if pixmap:
                  scaled_pixmap = pixmap.scaled(evidence_img_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                  evidence_img_label.setPixmap(scaled_pixmap)
                  evidence_img_label.setToolTip("Image de preuve fournie") 
             else:
                  evidence_img_label.setText("Preuve\nInvalide") 
                  evidence_img_label.setToolTip("Impossible de charger l'image de preuve") 
             bottom_layout.addWidget(evidence_img_label) 
        else:
             no_evidence_label = QLabel("<i>Aucune preuve fournie</i>") 
             no_evidence_label.setStyleSheet("font-size: 11px; color: #888;")
             bottom_layout.addWidget(no_evidence_label)


        bottom_layout.addStretch() 

        # Boutons d'action (Accepter/Rejeter pour le propriétaire sur les réclamations en attente)
        if context == 'owner_view' and claim_status == 'pending':
            accept_button = QPushButton(QIcon.fromTheme("dialog-ok-apply"), " Accepter") 
            accept_button.setStyleSheet("background-color: #4caf50; color: white; padding: 5px 10px; border-radius: 4px; font-size: 11px; border: none;")
            accept_button.setCursor(Qt.PointingHandCursor)
            accept_button.clicked.connect(lambda checked, cid=claim_data['claim_id'], iid=claim_data['id_objet_reclame']: self.handle_accept_claim(cid, iid))
            bottom_layout.addWidget(accept_button) 

            reject_button = QPushButton(QIcon.fromTheme("dialog-cancel"), " Rejeter") 
            reject_button.setStyleSheet("background-color: #f44336; color: white; padding: 5px 10px; border-radius: 4px; font-size: 11px; border: none;")
            reject_button.setCursor(Qt.PointingHandCursor)
            reject_button.clicked.connect(lambda checked, cid=claim_data['claim_id']: self.handle_reject_claim(cid))
            bottom_layout.addWidget(reject_button)

        main_layout.addLayout(bottom_layout)

        return claim_widget


    def handle_claim_button_click(self, item_id):
        """Ouvre le dialogue de réclamation lorsque 'Réclamer cet objet' est cliqué."""
        if not self.current_user:
             self.show_flash_message("Veuillez vous connecter pour soumettre une réclamation.", is_error=True) 
             return
        if not self.databases_connected:
             self.show_flash_message("Erreur de connexion à la base de données. Impossible de soumettre la réclamation.", is_error=True) 
             return
        # Vérifier si l'utilisateur a déjà réclamé cet objet 
        claims_on_this = get_claims_for_item(item_id)
        already_claimed = any(c['claimant_id'] == self.current_user['id'] for c in claims_on_this)
        if already_claimed:
              QMessageBox.information(self, "Déjà réclamé", "Vous avez déjà soumis une réclamation pour cet objet.") 
              return

        dialog = ClaimDialog(item_id, self)
        if dialog.exec_() == QDialog.Accepted:
            claim_data = dialog.get_claim_data()
            if claim_data:
                reason, evidence_data = claim_data
                success, message = submit_claim(item_id, self.current_user['id_utilisateur'], reason, evidence_data)
                if success:
                    self.show_flash_message(message) 
                    if self.stacked_widget.currentIndex() == 5: 
                        self.load_my_submitted_claims() 
                else:
                    self.show_flash_message(message, is_error=True)
            else:
                self.show_flash_message("Soumission de réclamation annulée ou échec de validation.", is_error=True) 


    def handle_accept_claim(self, claim_id, item_id):
        """Gère le clic sur le bouton 'Accepter' pour une réclamation."""
        reply = QMessageBox.question(self, "Confirmer l'acceptation",
                                     f"Êtes-vous sûr de vouloir accepter la réclamation {claim_id} pour l'objet {item_id} ?\n"
                                     "Cela marquera l'objet comme 'récupéré' et rejettera les autres réclamations en attente.", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No) 
        if reply == QMessageBox.Yes:
             if not self.databases_connected:
                  self.show_flash_message("Erreur de base de données. Impossible d'accepter la réclamation.", is_error=True)
                  return
             success, message = accept_claim(claim_id, item_id)
             if success:
                  self.show_flash_message(message) 
                  self.load_user_items() 
                  self.load_claims_on_my_items()
                  self.load_my_submitted_claims()
             else:
                  self.show_flash_message(f"Échec de l'acceptation de la réclamation : {message}", is_error=True)


    def handle_reject_claim(self, claim_id):
        """Gère le clic sur le bouton 'Rejeter' pour une réclamation."""
        reply = QMessageBox.question(self, 'Confirmer le rejet', 
                                     f"Êtes-vous sûr de vouloir rejeter la réclamation {claim_id} ?", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
             if not self.databases_connected:
                  self.show_flash_message("Erreur de base de données. Impossible de rejeter la réclamation.", is_error=True)
             success, message = reject_claim(claim_id)
             if success:
                  self.show_flash_message(f"Réclamation {claim_id} rejetée.") 
                  self.load_claims_on_my_items()
                  self.load_my_submitted_claims() 
             else:
                  self.show_flash_message(f"Échec du rejet de la réclamation : {message}", is_error=True) 


    def load_pixmap_from_data(self, image_data):
        """Charger en toute sécurité un QPixmap à partir de données binaires."""
        if not image_data:
            return None 
        try:
            pixmap = QPixmap() 
            buffer = QBuffer()
            buffer.setData(bytes(image_data)) 
            buffer.open(QIODevice.ReadOnly)
            loaded = pixmap.loadFromData(buffer.readAll()) 
            buffer.close()
            return pixmap if loaded else None
        except Exception as e:
            print(f"Erreur lors du chargement du pixmap depuis les données : {e}") 
            return None

    def clear_layout(self, layout):
        """Effacer tous les widgets d'un layout récursivement"""
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0) 
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    sub_layout = item.layout()
                    if sub_layout is not None:
                        self.clear_layout(sub_layout)

# --- Point d'entrée principal de l'application ---
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    font = QFont(FONT_FAMILY, 10)
    app.setFont(font)
    window = TawdrlikApp()
    window.show()

    def cleanup():
        global mysql_connection, mongo_client
        if mysql_connection and mysql_connection.is_connected():
            try:
                mysql_connection.close()
                print("Connexion MySQL fermée.") 
            except Exception as e:
                 print(f"Erreur lors de la fermeture de la connexion MySQL : {e}") 
        if mongo_client:
            try:
                mongo_client.close()
                print("Connexion MongoDB fermée.") 
            except Exception as e:
                 print(f"Erreur lors de la fermeture de la connexion MongoDB : {e}")

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()