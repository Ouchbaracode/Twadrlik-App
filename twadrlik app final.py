import sys
import re 
import datetime
import hashlib 
import mysql.connector
from pymongo import MongoClient
from bson.objectid import ObjectId 
from bson.binary import Binary # <-- Import Binary for MongoDB image storage
import base64 # <-- To handle potential large image data conversion if needed
import io # <-- Needed for QPixmap from bytes

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QLineEdit,
                            QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton,
                            QStackedWidget, QComboBox, QDateEdit, QTextEdit,
                            QListWidget, QListWidgetItem, QMessageBox, QGroupBox,
                            QScrollArea, QSizePolicy, QSpacerItem, QFileDialog,
                            QDialog, QDialogButtonBox) # <-- Import QFileDialog, QDialog, QDialogButtonBox
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPixmap
from PyQt5.QtCore import Qt, QDate, QBuffer, QIODevice, QTimer, QSize # <-- Import QBuffer, QIODevice, QTimer, QSize

# Global variables for database connections 
mysql_connection = None
mongo_client = None
mongo_db = None

# Database configuration
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Mohamed@mysql', 
    'database': 'tawdrlik_DB'
}

MONGODB_URI = "mongodb://localhost:27017/"
MONGODB_DB = "tawdrlikDB"

# App styling constants
PRIMARY_COLOR = "#3BAFDA"
BACKGROUND_COLOR = "#F9FAFB"
ACCENT_COLOR = "#1C3D5A"
FONT_FAMILY = "Arial" 


# --- Database Connection Functions ---

def connect_to_mysql():
    global mysql_connection
    if mysql_connection and mysql_connection.is_connected():
        return True # Already connected
    try:
        mysql_connection = mysql.connector.connect(**MYSQL_CONFIG, autocommit=False) # Disable autocommit for transactions
        # Test connection
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall() 
        cursor.close()
        print("MySQL connected successfully")
        return True
    except mysql.connector.Error as err:
        print(f"MySQL Error: {err}")
        QMessageBox.critical(None, "Database Error", f"MySQL Connection Failed: {err}")
        mysql_connection = None # Ensure it's None on failure
        return False

def connect_to_mongodb():
    global mongo_client, mongo_db
    if mongo_client is not None and mongo_db is not None:
         try:
              mongo_client.admin.command('ping')
              return True
         except Exception:
              print("MongoDB connection lost, attempting to reconnect...")
              mongo_client = None
              mongo_db = None
              # Fall through to reconnect logic
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000) # Add timeout
        # The ismaster command is cheap and does not require auth.
        mongo_client.admin.command('ismaster') # Verify connection
        mongo_db = mongo_client[MONGODB_DB]
        print("MongoDB connected successfully")
        return True
    except Exception as e:
        print(f"MongoDB Error: {e}")
        QMessageBox.critical(None, "Database Error", f"MongoDB Connection Failed: {e}")
        mongo_client = None
        mongo_db = None
        return False

def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

# --- User Authentication Functions ---
def register_user(username, email, password):
    """Register a new user in the MySQL database"""
    if not connect_to_mysql():
        return False, "Database not connected"
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        hashed_password = hash_password(password)

        # Check if email already exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return False, "Email already registered"

        # Check if username already exists
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            return False, "Username already taken"

        # Insert new user
        cursor.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, hashed_password)
        )
        mysql_connection.commit()   
        return True, "Registration successful!"
    except mysql.connector.Error as err:
        print(f"Registration error: {err}")
        mysql_connection.rollback() # Rollback changes on error
        return False, f"Registration failed: {err}"
    finally:
        if cursor:
            cursor.close()

def login_user(email, password):
    """Authenticate a user against the MySQL database"""
    if not connect_to_mysql():
        return False, "Database not connected"
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True) # Get results as dicts
        hashed_password = hash_password(password)

        cursor.execute(
            "SELECT id, username, email FROM users WHERE email = %s AND password = %s",
            (email, hashed_password)
        )
        user = cursor.fetchone()

        if user:
            return True, user 
        else:
            return False, "Invalid email or password"
    except mysql.connector.Error as err:
        print(f"Login error: {err}")
        return False, f"Login failed: {err}"
    finally:
        if cursor:
            cursor.close()

# --- Item Management Functions ---
def save_item(user_id, title, category, location, date, status, description, image_data=None):
    """Save item metadata to MySQL and details (description + image) to MongoDB"""
    if not connect_to_mysql() or not connect_to_mongodb():
        return False, "Database connection failed"

    mongo_id_obj = None
    mongo_id_str = None
    cursor = None

    try:
        # 1. Save description and image to MongoDB
        mongo_image_data = Binary(image_data) if image_data else None
        mongo_result = mongo_db.items_detail.insert_one({
            "description": description,
            "image": mongo_image_data
        })
        mongo_id_obj = mongo_result.inserted_id
        mongo_id_str = str(mongo_id_obj)

        # 2. Save metadata to MySQL, linking to the MongoDB document
        cursor = mysql_connection.cursor()
        cursor.execute(
            """INSERT INTO items (user_id, title, category, location, date, status, mongo_id, description)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, title, category, location, date, status, mongo_id_str, description)
            )
        # We forgot the description field in the items table in the CREATE statement.
        # Let's assume it exists or decide to only rely on MongoDB for description.
        # For now, assuming description is NOT in the MySQL items table.

        mysql_connection.commit()
        return True, "Item saved successfully!"

    except Exception as e:
        print(f"Error saving item: {e}")
        # Rollback logic: If MySQL fails after MongoDB insert, delete the MongoDB doc
        if mongo_id_obj:
            try:
                mongo_db.items_detail.delete_one({"_id": mongo_id_obj})
                print(f"Cleaned up MongoDB entry {mongo_id_str} due to error.")
            except Exception as mongo_del_err:
                print(f"Error cleaning up MongoDB entry {mongo_id_str}: {mongo_del_err}")
        # Rollback MySQL
        try:
            mysql_connection.rollback()
        except Exception as rollback_err:
            print(f"Error rolling back MySQL transaction: {rollback_err}")

        return False, f"Failed to save item: {e}"
    finally:
        if cursor:
            cursor.close()

def get_all_items(filter_category=None, filter_location=None, include_recovered=False):
    """Retrieve items (excluding recovered by default), join with user, fetch details from MongoDB"""
    if not connect_to_mysql() or not connect_to_mongodb():
        print("Database connection failed in get_all_items")
        return []

    items = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)

        query = """
        SELECT i.id, i.user_id, i.title, i.category, i.location, i.date, i.status, i.mongo_id, i.created_at,
               u.username AS owner_username
        FROM items i
        JOIN users u ON i.user_id = u.id
        """

        params = []
        conditions = []

        # Exclude recovered items unless specified
        if not include_recovered:
            conditions.append("i.status != %s")
            params.append('recovered')

        if filter_category and filter_category != "All Categories":
            conditions.append("i.category = %s")
            params.append(filter_category)

        if filter_location and filter_location != "All Locations":
            conditions.append("i.location = %s")
            params.append(filter_location)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY i.status, i.date DESC, i.created_at DESC" # Show found/lost first

        cursor.execute(query, tuple(params)) # Pass params as tuple
        items_mysql = cursor.fetchall()

        # Fetch details from MongoDB for each item
        for item_mysql in items_mysql:
            mongo_id_str = item_mysql.get('mongo_id')
            description = 'Details unavailable'
            image_data = None
            if mongo_id_str:
                try:
                    mongo_object_id = ObjectId(mongo_id_str)
                    item_detail = mongo_db.items_detail.find_one({"_id": mongo_object_id})
                    if item_detail:
                        description = item_detail.get('description', 'No description found')
                        image_data = item_detail.get('image') # This is BSON Binary or None
                    else:
                        print(f"No MongoDB document found for mongo_id: {mongo_id_str}")
                        description = 'Details missing in secondary storage'
                except Exception as e:
                    print(f"Error fetching/parsing MongoDB document ({mongo_id_str}): {e}")
                    description = 'Error fetching details'

            item_mysql['description'] = description
            item_mysql['image_data'] = image_data
            items.append(item_mysql)

        return items
    except mysql.connector.Error as e:
        print(f"Error fetching items from MySQL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred during item retrieval: {e}")
        return items # Return potentially partially fetched items
    finally:
        if cursor:
            cursor.close()


def get_user_items(user_id):
    """Get items posted by a specific user, including recovered ones, fetch details from MongoDB"""
    if not connect_to_mysql() or not connect_to_mongodb():
        print("Database connection failed in get_user_items")
        return []

    items = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT i.id, i.user_id, i.title, i.category, i.location, i.date, i.status, i.mongo_id, i.created_at,
                      u.username AS owner_username
               FROM items i
               JOIN users u ON i.user_id = u.id
               WHERE i.user_id = %s
               ORDER BY i.created_at DESC""",
            (user_id,)
        )
        items_mysql = cursor.fetchall()

        # Fetch details from MongoDB
        for item_mysql in items_mysql:
            mongo_id_str = item_mysql.get('mongo_id')
            description = 'Details unavailable'
            image_data = None
            if mongo_id_str:
                try:
                    mongo_object_id = ObjectId(mongo_id_str)
                    item_detail = mongo_db.items_detail.find_one({"_id": mongo_object_id})
                    if item_detail:
                        description = item_detail.get('description', 'No description found')
                        image_data = item_detail.get('image') # BSON Binary or None
                    else:
                        print(f"No MongoDB document found for user item mongo_id: {mongo_id_str}")
                        description = 'Details missing in secondary storage'
                except Exception as e:
                    print(f"Error fetching/parsing MongoDB document ({mongo_id_str}) for user item: {e}")
                    description = 'Error fetching details'

            item_mysql['description'] = description
            item_mysql['image_data'] = image_data
            items.append(item_mysql)

        return items
    except mysql.connector.Error as e:
        print(f"Error fetching user items from MySQL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred during user item retrieval: {e}")
        return items # Return potentially partially fetched items
    finally:
        if cursor:
            cursor.close()

def get_item_owner(item_id):
    """Get the user_id of the item's owner."""
    if not connect_to_mysql():
        print("Database connection failed in get_item_owner")
        return None
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT user_id FROM items WHERE id = %s", (item_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except mysql.connector.Error as e:
        print(f"Error fetching item owner: {e}")
        return None
    finally:
        if cursor:
            cursor.close()


def get_unique_categories():
    """Get a list of unique categories from the items table"""
    if not connect_to_mysql(): return ["All Categories"]
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT DISTINCT category FROM items WHERE category IS NOT NULL AND category != '' ORDER BY category")
        categories = [row[0] for row in cursor.fetchall()]
        return ["All Categories"] + categories
    except mysql.connector.Error as e:
        print(f"Error fetching categories: {e}")
        return ["All Categories"]
    finally:
        if cursor:
            cursor.close()

def get_unique_locations():
    """Get a list of unique locations from the items table"""
    if not connect_to_mysql(): return ["All Locations"]
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute("SELECT DISTINCT location FROM items WHERE location IS NOT NULL AND location != '' ORDER BY location")
        locations = [row[0] for row in cursor.fetchall()]
        return ["All Locations"] + locations
    except mysql.connector.Error as e:
        print(f"Error fetching locations: {e}")
        return ["All Locations"]
    finally:
        if cursor:
            cursor.close()


# --- Claim Management Functions ---

def submit_claim(item_id, claimant_id, reason, evidence_image_data=None):
    """Submit a claim for an item."""
    if not connect_to_mysql() or not connect_to_mongodb():
        return False, "Database connection failed"

    mongo_detail_id_obj = None
    mongo_detail_id_str = None
    cursor = None

    try:
        # 1. (Optional) Save evidence image to MongoDB claims_detail collection
        if evidence_image_data:
            mongo_result = mongo_db.claims_detail.insert_one({
                "evidence_image": Binary(evidence_image_data),
                "notes": f"Evidence for claim on item {item_id} by user {claimant_id}" # Example note
            })
            mongo_detail_id_obj = mongo_result.inserted_id
            mongo_detail_id_str = str(mongo_detail_id_obj)

        # 2. Save claim details to MySQL
        cursor = mysql_connection.cursor()
        cursor.execute(
            """INSERT INTO claims (item_id, claimant_id, reason, status, mongo_detail_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (item_id, claimant_id, reason, 'pending', mongo_detail_id_str, datetime.datetime.now())
        )
        mysql_connection.commit()
        return True, "Claim submitted successfully!"

    except Exception as e:
        print(f"Error submitting claim: {e}")
        # Rollback logic: If MySQL fails after MongoDB insert, delete the MongoDB doc
        if mongo_detail_id_obj:
            try:
                mongo_db.claims_detail.delete_one({"_id": mongo_detail_id_obj})
                print(f"Cleaned up MongoDB claim detail {mongo_detail_id_str} due to error.")
            except Exception as mongo_del_err:
                print(f"Error cleaning up MongoDB claim detail {mongo_detail_id_str}: {mongo_del_err}")
        # Rollback MySQL
        try:
            mysql_connection.rollback()
        except Exception as rollback_err:
            print(f"Error rolling back MySQL transaction: {rollback_err}")

        return False, f"Failed to submit claim: {e}"
    finally:
        if cursor:
            cursor.close()


def get_claims_for_item(item_id):
    """Retrieve all claims for a specific item, joining with claimant user info."""
    if not connect_to_mysql():
        print("Database connection failed in get_claims_for_item")
        return []
    claims = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        query = """
        SELECT c.id AS claim_id, c.item_id, c.claimant_id, c.reason, c.status AS claim_status,
               c.mongo_detail_id, c.created_at AS claim_created_at,
               u.username AS claimant_username
        FROM claims c
        JOIN users u ON c.claimant_id = u.id
        WHERE c.item_id = %s
        ORDER BY c.created_at DESC
        """
        cursor.execute(query, (item_id,))
        claims_mysql = cursor.fetchall()

        # Optionally fetch evidence image data from MongoDB for each claim
        for claim in claims_mysql:
            mongo_detail_id_str = claim.get('mongo_detail_id')
            evidence_image_data = None
            if mongo_detail_id_str:
                try:
                    claim_detail = mongo_db.claims_detail.find_one({"_id": ObjectId(mongo_detail_id_str)})
                    if claim_detail:
                        evidence_image_data = claim_detail.get('evidence_image')
                except Exception as e:
                    print(f"Error fetching claim detail ({mongo_detail_id_str}): {e}")
            claim['evidence_image_data'] = evidence_image_data
            claims.append(claim)

        return claims
    except mysql.connector.Error as e:
        print(f"Error fetching claims for item from MySQL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred during claim retrieval for item: {e}")
        return claims # Return potentially partially fetched claims
    finally:
        if cursor:
            cursor.close()


def get_claims_by_claimant(claimant_id):
    """Retrieve all claims made by a specific user, joining with item info."""
    if not connect_to_mysql():
        print("Database connection failed in get_claims_by_claimant")
        return []
    claims = []
    cursor = None
    try:
        cursor = mysql_connection.cursor(dictionary=True)
        query = """
        SELECT c.id AS claim_id, c.item_id, c.claimant_id, c.reason, c.status AS claim_status,
               c.mongo_detail_id, c.created_at AS claim_created_at,
               i.title AS item_title, i.status AS item_status, i.mongo_id AS item_mongo_id
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.claimant_id = %s
        ORDER BY c.created_at DESC
        """
        cursor.execute(query, (claimant_id,))
        claims_mysql = cursor.fetchall()

        # Fetch details (item image, claim evidence image) from MongoDB
        for claim in claims_mysql:
            # Fetch claim evidence image
            mongo_detail_id_str = claim.get('mongo_detail_id')
            evidence_image_data = None
            if mongo_detail_id_str:
                try:
                    claim_detail = mongo_db.claims_detail.find_one({"_id": ObjectId(mongo_detail_id_str)})
                    if claim_detail:
                        evidence_image_data = claim_detail.get('evidence_image')
                except Exception as e:
                    print(f"Error fetching claim detail ({mongo_detail_id_str}): {e}")
            claim['evidence_image_data'] = evidence_image_data

            # Fetch item image
            item_mongo_id_str = claim.get('item_mongo_id')
            item_image_data = None
            if item_mongo_id_str:
                 try:
                     item_detail = mongo_db.items_detail.find_one({"_id": ObjectId(item_mongo_id_str)})
                     if item_detail:
                         item_image_data = item_detail.get('image')
                 except Exception as e:
                      print(f"Error fetching item detail for claim ({item_mongo_id_str}): {e}")
            claim['item_image_data'] = item_image_data # Add item image to claim dict

            claims.append(claim)

        return claims
    except mysql.connector.Error as e:
        print(f"Error fetching claims by claimant from MySQL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred during claim retrieval by claimant: {e}")
        return claims # Return potentially partially fetched claims
    finally:
        if cursor:
            cursor.close()


def update_claim_status(claim_id, new_status):
    """Update the status of a specific claim."""
    if not connect_to_mysql():
        return False, "Database connection failed"
    cursor = None
    try:
        cursor = mysql_connection.cursor()
        cursor.execute(
            "UPDATE claims SET status = %s WHERE id = %s",
            (new_status, claim_id)
        )
        mysql_connection.commit()
        return True, f"Claim {claim_id} status updated to {new_status}"
    except mysql.connector.Error as err:
        print(f"Error updating claim status: {err}")
        mysql_connection.rollback()
        return False, f"Failed to update claim status: {err}"
    finally:
        if cursor:
            cursor.close()


def accept_claim(claim_id, item_id):
    """Accept a claim: update claim status, item status, reject other pending claims."""
    if not connect_to_mysql():
        return False, "Database connection failed"
    cursor = None
    try:
        cursor = mysql_connection.cursor()

        # 1. Update the accepted claim's status
        cursor.execute("UPDATE claims SET status = %s WHERE id = %s", ('accepted', claim_id))
        if cursor.rowcount == 0:
            raise Exception(f"Claim ID {claim_id} not found.")

        # 2. Update the item's status to 'recovered'
        cursor.execute("UPDATE items SET status = %s WHERE id = %s", ('recovered', item_id))
        if cursor.rowcount == 0:
             raise Exception(f"Item ID {item_id} not found or already recovered.") # Or handle differently

        # 3. Reject all other *pending* claims for the same item
        cursor.execute(
            "UPDATE claims SET status = %s WHERE item_id = %s AND status = %s AND id != %s",
            ('rejected', item_id, 'pending', claim_id)
        )
        rejected_count = cursor.rowcount # How many other claims were rejected

        mysql_connection.commit()
        return True, f"Claim {claim_id} accepted. Item {item_id} marked as recovered. {rejected_count} other pending claims rejected."

    except Exception as err: # Catch MySQL errors and others (like claim/item not found)
        print(f"Error accepting claim: {err}")
        mysql_connection.rollback()
        return False, f"Failed to accept claim: {err}"
    finally:
        if cursor:
            cursor.close()


def reject_claim(claim_id):
    """Reject a specific claim."""
    return update_claim_status(claim_id, 'rejected')


# --- PyQt5 UI Classes ---

class ClaimDialog(QDialog):
    """Dialog for submitting a claim."""
    def __init__(self, item_id, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.selected_evidence_path = None
        self.evidence_image_data = None

        self.setWindowTitle("Submit Claim")
        self.setMinimumWidth(450)
        self.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # Reason Field
        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("Explain why you believe this item is yours...")
        self.reason_edit.setMinimumHeight(100)
        self.reason_edit.setStyleSheet("padding: 8px; border: 1px solid #ccc; border-radius: 4px; background-color: white;")
        form_layout.addRow(QLabel("<b>Reason for Claim:</b>*"), self.reason_edit)

        # Evidence Image (Optional)
        evidence_layout = QHBoxLayout()
        self.select_evidence_button = QPushButton(QIcon.fromTheme("insert-image"), " Select Evidence Image (Optional)...")
        self.select_evidence_button.setStyleSheet(f"""
            QPushButton {{ background-color: #e0e0e0; color: #333; padding: 8px 12px;
                           border-radius: 5px; border: none; font-size: 13px;}}
            QPushButton:hover {{ background-color: #d5d5d5; }}
        """)
        self.select_evidence_button.setCursor(Qt.PointingHandCursor)
        self.select_evidence_button.clicked.connect(self.select_evidence_file)
        self.evidence_preview_label = QLabel("No evidence selected.")
        self.evidence_preview_label.setStyleSheet("font-style: italic; color: #777; margin-left: 10px;")
        self.evidence_preview_label.setMinimumWidth(150)

        evidence_layout.addWidget(self.select_evidence_button)
        evidence_layout.addWidget(self.evidence_preview_label)
        evidence_layout.addStretch()
        form_layout.addRow(QLabel("<b>Evidence:</b>"), evidence_layout)

        layout.addLayout(form_layout)

        # Dialog Buttons (Submit, Cancel)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("Submit Claim")
        button_box.button(QDialogButtonBox.Ok).setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 8px 20px; border-radius: 5px; font-weight: bold;")
        button_box.button(QDialogButtonBox.Cancel).setStyleSheet("background-color: #aaa; color: white; padding: 8px 20px; border-radius: 5px;")

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def select_evidence_file(self):
        """Open a file dialog to select an evidence image."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Evidence Image", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.gif)", options=options)
        if file_path:
            try:
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    raise ValueError("Invalid image file")

                # Read image data for potential submission
                with open(file_path, 'rb') as f:
                    self.evidence_image_data = f.read()
                    if len(self.evidence_image_data) > 16 * 1024 * 1024: # Check size
                        QMessageBox.warning(self, "Image Too Large", "Evidence image must be under 16MB.")
                        self.evidence_image_data = None
                        self.selected_evidence_path = None
                        self.evidence_preview_label.setText("Image too large.")
                        self.evidence_preview_label.setPixmap(QPixmap()) # Clear preview
                        return

                self.selected_evidence_path = file_path
                # Display a small preview
                preview_pixmap = pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.evidence_preview_label.setPixmap(preview_pixmap)
                self.evidence_preview_label.setToolTip(file_path)

            except Exception as e:
                QMessageBox.warning(self, "Image Error", f"Could not load or read image: {e}")
                self.selected_evidence_path = None
                self.evidence_image_data = None
                self.evidence_preview_label.setText("Error loading image.")
                self.evidence_preview_label.setPixmap(QPixmap()) # Clear preview


    def get_claim_data(self):
        """Return the claim reason and image data."""
        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Missing Information", "Please provide a reason for your claim.")
            return None
        return reason, self.evidence_image_data # evidence_image_data is None if not selected/valid


class TawdrlikApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # Initialize database connections (and setup tables if first run)
        # setup_database_tables() # Uncomment this line for the very first run

        if not connect_to_mysql() or not connect_to_mongodb():
            QMessageBox.critical(self, "Startup Error", "Failed to connect to databases. Application cannot start.")
            # Don't exit immediately, let the user see the message.
            # The UI might be partially usable but DB operations will fail.
            # Consider disabling buttons or showing a persistent error message.
            self.databases_connected = False
        else:
            self.databases_connected = True

        self.current_user = None # Will store user dict: {'id': ?, 'username': ?, 'email': ?}
        self.selected_image_path = None # For posting items

        self.setWindowTitle("Tawdrlik - Lost & Found System")
        self.setGeometry(100, 100, 950, 750) # Slightly larger window
        self.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")

        # Main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0) # No margin for main layout

        # Create stacked widget for different pages
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget, 1) # Give stack widget stretch factor

        # Create different pages
        self.setup_login_page()         # Index 0
        self.setup_register_page()      # Index 1
        self.setup_home_page()          # Index 2
        self.setup_post_item_page()     # Index 3
        self.setup_view_items_page()    # Index 4
        self.setup_profile_page()       # Index 5 (Now includes claim management)

        # Flash message label at the bottom
        self.flash_message_label = QLabel("")
        self.flash_message_label.setAlignment(Qt.AlignCenter)
        self.flash_message_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") # Initial style (success)
        self.flash_message_label.setVisible(False) # Initially hidden
        self.flash_timer = QTimer(self)
        self.flash_timer.setSingleShot(True)
        self.flash_timer.timeout.connect(lambda: self.flash_message_label.setVisible(False))

        self.main_layout.addWidget(self.flash_message_label) # Add below stacked widget

        # Start with login page
        self.stacked_widget.setCurrentIndex(0)


    def show_flash_message(self, message, duration=3000, is_error=False):
        """Display a temporary message at the bottom."""
        if is_error:
            self.flash_message_label.setStyleSheet("background-color: #f44336; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") # Error style
        else:
            self.flash_message_label.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; border-radius: 0px;") # Success style
        self.flash_message_label.setText(message)
        self.flash_message_label.setVisible(True)
        self.flash_timer.start(duration)


    def setup_login_page(self):
        login_widget = QWidget()
        login_layout = QVBoxLayout(login_widget)
        login_layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel("Tawdrlik")
        title_label.setFont(QFont(FONT_FAMILY, 24, QFont.Bold))
        title_label.setStyleSheet(f"color: {ACCENT_COLOR};")
        title_label.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(title_label)

        subtitle_label = QLabel("Lost & Found System")
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
        self.login_email.setPlaceholderText("Enter your email")
        self.login_email.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        login_form.addRow("Email:", self.login_email)

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Enter your password")
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        login_form.addRow("Password:", self.login_password)

        form_layout.addLayout(login_form)
        form_layout.addSpacing(20)

        login_button = QPushButton("Login")
        login_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        login_button.clicked.connect(self.handle_login)
        form_layout.addWidget(login_button)

        register_layout = QHBoxLayout()
        register_label = QLabel("Don't have an account?")
        register_button = QPushButton("Register")
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

        title_label = QLabel("Create Account")
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
        self.register_username.setPlaceholderText("Choose a username")
        self.register_username.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Username:", self.register_username)

        self.register_email = QLineEdit()
        self.register_email.setPlaceholderText("Enter your email")
        self.register_email.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Email:", self.register_email)

        self.register_password = QLineEdit()
        self.register_password.setPlaceholderText("Create a password (min 6 chars)")
        self.register_password.setEchoMode(QLineEdit.Password)
        self.register_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Password:", self.register_password)

        self.register_confirm_password = QLineEdit()
        self.register_confirm_password.setPlaceholderText("Confirm your password")
        self.register_confirm_password.setEchoMode(QLineEdit.Password)
        self.register_confirm_password.setStyleSheet("padding: 10px; border-radius: 5px; border: 1px solid #ddd;")
        register_form.addRow("Confirm Password:", self.register_confirm_password)

        form_layout.addLayout(register_form)
        form_layout.addSpacing(20)

        register_button = QPushButton("Register")
        register_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 10px; border-radius: 5px; font-weight: bold;")
        register_button.clicked.connect(self.handle_register)
        form_layout.addWidget(register_button)

        login_layout = QHBoxLayout()
        login_label = QLabel("Already have an account?")
        login_button = QPushButton("Login")
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
        home_layout.setContentsMargins(10,10,10,10) # Reduce margins slightly

        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 10px; padding: 15px 20px; margin-bottom: 15px;")
        header_layout = QHBoxLayout(header_container)

        self.welcome_label = QLabel("Welcome back!")
        self.welcome_label.setFont(QFont(FONT_FAMILY, 15, QFont.Bold)) # Slightly smaller
        self.welcome_label.setStyleSheet("color: white;")

        profile_button = QPushButton(QIcon.fromTheme("user-identity"), " My Profile & Claims") # Updated text
        profile_button.setStyleSheet("background-color: white; color: #3BAFDA; padding: 8px 15px; border-radius: 5px; font-weight: bold; border: none;")
        profile_button.setCursor(Qt.PointingHandCursor)
        profile_button.setIconSize(QSize(18, 18)) # Adjust icon size
        profile_button.clicked.connect(self.show_profile_page) # Connect to profile page

        logout_button = QPushButton(QIcon.fromTheme("application-exit"), " Logout")
        logout_button.setStyleSheet("background-color: #f44336; color: white; padding: 8px 15px; border-radius: 5px; font-weight: bold; border: none;")
        logout_button.setCursor(Qt.PointingHandCursor)
        logout_button.setIconSize(QSize(18, 18))
        logout_button.clicked.connect(self.handle_logout)

        header_layout.addWidget(self.welcome_label)
        header_layout.addStretch()
        header_layout.addWidget(profile_button)
        header_layout.addWidget(logout_button)

        home_layout.addWidget(header_container)

        # Main content with feature buttons
        main_content = QWidget()
        main_content.setStyleSheet("background-color: white; border-radius: 10px; padding: 25px;")
        main_content_layout = QVBoxLayout(main_content)

        intro_label = QLabel("What would you like to do today?")
        intro_label.setFont(QFont(FONT_FAMILY, 14))
        intro_label.setAlignment(Qt.AlignCenter)
        intro_label.setStyleSheet(f"color: {ACCENT_COLOR}; margin-bottom: 20px;")

        main_content_layout.addWidget(intro_label)
        main_content_layout.addSpacing(20)

        # Button grid
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(20) # Add spacing between buttons

        button_style = """
            QPushButton {
                padding: 35px; border-radius: 10px; font-size: 15px; font-weight: bold; color: white;
            }
            QPushButton:hover { border: 2px solid black; }
        """

        lost_item_button = QPushButton(QIcon.fromTheme("edit-find-replace"), "\nPost Lost Item")
        lost_item_button.setStyleSheet(f"background-color: #ff9800; {button_style}")
        lost_item_button.setIconSize(QSize(48,48))
        lost_item_button.setCursor(Qt.PointingHandCursor)
        lost_item_button.clicked.connect(lambda: self.show_post_item_page("lost"))

        found_item_button = QPushButton(QIcon.fromTheme("emblem-important"), "\nPost Found Item")
        found_item_button.setStyleSheet(f"background-color: #4caf50; {button_style}")
        found_item_button.setIconSize(QSize(48,48))
        found_item_button.setCursor(Qt.PointingHandCursor)
        found_item_button.clicked.connect(lambda: self.show_post_item_page("found"))

        view_items_button = QPushButton(QIcon.fromTheme("system-search"), "\nView All Items")
        view_items_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; {button_style}")
        view_items_button.setIconSize(QSize(48,48))
        view_items_button.setCursor(Qt.PointingHandCursor)
        view_items_button.clicked.connect(self.show_view_items_page)

        buttons_layout.addWidget(lost_item_button)
        buttons_layout.addWidget(found_item_button)
        buttons_layout.addWidget(view_items_button)

        main_content_layout.addLayout(buttons_layout)
        home_layout.addWidget(main_content, 1) # Give content stretch factor

        self.stacked_widget.addWidget(home_widget)

    def setup_post_item_page(self):
        # ... (Post item page setup - mostly unchanged, ensure image preview works) ...
        post_item_widget = QWidget()
        post_layout = QVBoxLayout(post_item_widget)
        post_layout.setContentsMargins(20, 20, 20, 20)

        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px; margin-bottom: 25px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        self.post_title_label = QLabel("Post Item")
        self.post_title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        self.post_title_label.setStyleSheet("color: white;")

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Back to Home")
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } QPushButton:hover { background-color: #e0f7ff; }")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setIconSize(back_button.sizeHint() * 0.6) # Adjust icon size
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

        field_style = "padding: 12px; border-radius: 5px; border: 1px solid #ccc; font-size: 14px;"

        self.item_title = QLineEdit()
        self.item_title.setPlaceholderText("e.g., Black Wallet, iPhone 13")
        self.item_title.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Title:</b>*"), self.item_title)

        self.item_category = QComboBox()
        self.item_category.addItems(["Electronics", "Clothing", "Documents", "Keys", "Bags", "Jewelry", "Books", "Wallets/Purses", "Other"])
        self.item_category.setStyleSheet(field_style + " padding-right: 15px;")
        post_form.addRow(QLabel("<b>Category:</b>"), self.item_category)

        self.item_location = QLineEdit()
        self.item_location.setPlaceholderText("e.g., Main Library, City Park Bench")
        self.item_location.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Location:</b>*"), self.item_location)

        self.item_date = QDateEdit()
        self.item_date.setDate(QDate.currentDate())
        self.item_date.setCalendarPopup(True)
        self.item_date.setDisplayFormat("yyyy-MM-dd")
        self.item_date.setStyleSheet(field_style)
        post_form.addRow(QLabel("<b>Date Lost/Found:</b>"), self.item_date)

        self.item_description = QTextEdit()
        self.item_description.setPlaceholderText("Provide details: color, brand, specific marks, contents...")
        self.item_description.setStyleSheet(field_style)
        self.item_description.setMinimumHeight(100) # Reduced height slightly
        post_form.addRow(QLabel("<b>Description:</b>*"), self.item_description)

        image_layout = QHBoxLayout()
        self.select_image_button = QPushButton(QIcon.fromTheme("insert-image"), " Select Image...")
        self.select_image_button.setStyleSheet(f"QPushButton {{ background-color: #e0e0e0; color: #333; padding: 10px 15px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; }} QPushButton:hover {{ background-color: #d5d5d5; }}")
        self.select_image_button.setCursor(Qt.PointingHandCursor)
        self.select_image_button.clicked.connect(self.select_image_file)

        self.image_preview_label = QLabel() # Label to hold the pixmap
        self.image_preview_label.setFixedSize(80, 80) # Fixed size for preview
        self.image_preview_label.setAlignment(Qt.AlignCenter)
        self.image_preview_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 4px;")
        self.image_preview_label.setText("No Image\nSelected")
        self.image_preview_label.setToolTip("Image preview")


        image_layout.addWidget(self.select_image_button)
        image_layout.addWidget(self.image_preview_label)
        image_layout.addStretch()

        post_form.addRow(QLabel("<b>Image:</b>"), image_layout) # Changed label, made optional? Let's keep required for now

        form_layout.addLayout(post_form)
        form_layout.addSpacing(30)

        self.submit_item_button = QPushButton("Submit Item")
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
        self.current_item_status = "lost" # Default

    def select_image_file(self):
        """Open a file dialog to select an image for posting."""
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Item Image", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.gif)", options=options)
        if file_path:
            try:
                pixmap = QPixmap(file_path)
                if pixmap.isNull():
                    raise ValueError("Invalid image file")

                 # Check file size before storing path (optional but good)
                with open(file_path, 'rb') as f:
                     image_data_temp = f.read()
                     if len(image_data_temp) > 16 * 1024 * 1024:
                          QMessageBox.warning(self, "Image Too Large", "Item image must be under 16MB.")
                          return # Don't update path or preview

                self.selected_image_path = file_path
                # Display a thumbnail preview
                preview_pixmap = pixmap.scaled(self.image_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_preview_label.setPixmap(preview_pixmap)
                self.image_preview_label.setToolTip(file_path) # Show full path on hover

            except Exception as e:
                 QMessageBox.warning(self, "Image Error", f"Could not load image: {e}")
                 self.selected_image_path = None
                 self.image_preview_label.clear()
                 self.image_preview_label.setText("Error")
                 self.image_preview_label.setToolTip("Error loading image")


    def setup_view_items_page(self):
        # ... (View items page setup - Add filtering logic, ensure items list layout exists) ...
        view_items_widget = QWidget()
        view_layout = QVBoxLayout(view_items_widget)
        view_layout.setContentsMargins(20, 20, 20, 20)

        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px; margin-bottom: 20px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        title_label = QLabel("Browse Items")
        title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        title_label.setStyleSheet("color: white;")

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Back to Home")
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } QPushButton:hover { background-color: #e0f7ff; }")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setIconSize(back_button.sizeHint() * 0.6)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(back_button)

        view_layout.addWidget(header_container)

        # Filter section
        filter_container = QWidget()
        filter_container.setStyleSheet("background-color: white; border-radius: 8px; padding: 18px 25px; margin-bottom: 20px; border: 1px solid #e0e0e0;")
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setSpacing(15)

        filter_label = QLabel("Filter by:")
        filter_label.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        filter_label.setStyleSheet(f"color: {ACCENT_COLOR};")

        combo_style = "QComboBox { padding: 10px; min-width: 180px; font-size: 14px; background-color: white; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background-color: white; selection-background-color: #e0f7ff; selection-color: black; }"

        self.category_filter = QComboBox()
        self.category_filter.addItem("All Categories")
        self.category_filter.setStyleSheet(combo_style)
        self.category_filter.setCursor(Qt.PointingHandCursor)

        self.location_filter = QComboBox()
        self.location_filter.addItem("All Locations")
        self.location_filter.setStyleSheet(combo_style)
        self.location_filter.setCursor(Qt.PointingHandCursor)

        apply_filter_button = QPushButton(QIcon.fromTheme("edit-find"), " Apply Filter")
        apply_filter_button.setStyleSheet(f"QPushButton {{ background-color: {ACCENT_COLOR}; color: white; padding: 10px 20px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; }} QPushButton:hover {{ background-color: #162d40; }}")
        apply_filter_button.setCursor(Qt.PointingHandCursor)
        apply_filter_button.setIconSize(apply_filter_button.sizeHint() * 0.6)
        apply_filter_button.clicked.connect(self.apply_item_filters)

        reset_filter_button = QPushButton(QIcon.fromTheme("edit-clear"), " Reset")
        reset_filter_button.setStyleSheet("QPushButton { background-color: #e0e0e0; color: #333; padding: 10px 20px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } QPushButton:hover { background-color: #d5d5d5; }")
        reset_filter_button.setCursor(Qt.PointingHandCursor)
        reset_filter_button.setIconSize(reset_filter_button.sizeHint() * 0.6)
        reset_filter_button.clicked.connect(self.reset_item_filters)

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(QLabel("Category:"))
        filter_layout.addWidget(self.category_filter)
        filter_layout.addWidget(QLabel("Location:"))
        filter_layout.addWidget(self.location_filter)
        filter_layout.addSpacing(10)
        filter_layout.addWidget(apply_filter_button)
        filter_layout.addWidget(reset_filter_button)
        filter_layout.addStretch()

        view_layout.addWidget(filter_container)

        # Items list area (Scrollable)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none; background-color: transparent;")

        scroll_content = QWidget()
        self.items_list_layout = QVBoxLayout(scroll_content) # Layout for item cards
        self.items_list_layout.setAlignment(Qt.AlignTop)
        self.items_list_layout.setSpacing(18)
        self.items_list_layout.setContentsMargins(5, 5, 10, 5)

        scroll_area.setWidget(scroll_content)
        view_layout.addWidget(scroll_area)

        self.stacked_widget.addWidget(view_items_widget)


    def setup_profile_page(self):
        """Setup the profile page, including sections for user items and claims."""
        profile_widget = QWidget()
        profile_layout = QVBoxLayout(profile_widget)
        profile_layout.setContentsMargins(20, 20, 20, 20)
        profile_layout.setSpacing(20) # Overall spacing

        # Header
        header_container = QWidget()
        header_container.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border-radius: 8px; padding: 15px 25px;")
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0,0,0,0)

        title_label = QLabel("My Profile & Claims Management")
        title_label.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        title_label.setStyleSheet("color: white;")

        back_button = QPushButton(QIcon.fromTheme("go-previous"), " Back to Home")
        back_button.setStyleSheet("QPushButton { background-color: white; color: #3BAFDA; padding: 10px 18px; border-radius: 5px; font-weight: bold; font-size: 14px; border: none; } QPushButton:hover { background-color: #e0f7ff; }")
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setIconSize(back_button.sizeHint() * 0.6)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(back_button)
        profile_layout.addWidget(header_container)

        # --- User Info Section ---
        user_info_group = QGroupBox("User Information")
        user_info_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        user_info_container_layout = QVBoxLayout(user_info_group) # Use layout inside groupbox

        user_info_container_layout.setSpacing(8)
        self.profile_username_label = QLabel("Username: Loading...")
        self.profile_username_label.setFont(QFont(FONT_FAMILY, 14))
        self.profile_email_label = QLabel("Email: Loading...")
        self.profile_email_label.setFont(QFont(FONT_FAMILY, 14))
        user_info_container_layout.addWidget(self.profile_username_label)
        user_info_container_layout.addWidget(self.profile_email_label)
        profile_layout.addWidget(user_info_group)


        # --- Splitter for My Items and Claims ---
        splitter = QWidget() # Using a simple widget container for now
        splitter_layout = QHBoxLayout(splitter)
        splitter_layout.setSpacing(20)
        profile_layout.addWidget(splitter, 1) # Make this section expandable


        # --- Left Side: My Posted Items ---
        my_items_group = QGroupBox("My Posted Items")
        my_items_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        my_items_layout = QVBoxLayout(my_items_group)

        items_scroll_area = QScrollArea()
        items_scroll_area.setWidgetResizable(True)
        items_scroll_area.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: white;")
        items_scroll_content = QWidget()
        self.user_items_layout = QVBoxLayout(items_scroll_content) # Layout for user's item cards
        self.user_items_layout.setAlignment(Qt.AlignTop)
        self.user_items_layout.setSpacing(15)
        self.user_items_layout.setContentsMargins(10, 10, 10, 10)
        items_scroll_area.setWidget(items_scroll_content)
        my_items_layout.addWidget(items_scroll_area)
        splitter_layout.addWidget(my_items_group)


        # --- Right Side: Claims Management ---
        claims_management_group = QGroupBox("Claims Management")
        claims_management_group.setStyleSheet("QGroupBox { font-size: 14px; font-weight: bold; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }")
        claims_management_layout = QVBoxLayout(claims_management_group)
        claims_management_layout.setSpacing(15)

        # Claims on My Items (for Owners)
        claims_on_my_items_group = QGroupBox("Claims Received on My Items")
        claims_on_my_items_layout_outer = QVBoxLayout(claims_on_my_items_group)
        claims_on_items_scroll = QScrollArea()
        claims_on_items_scroll.setWidgetResizable(True)
        claims_on_items_scroll.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: #f8f8f8;") # Slightly different bg
        claims_on_items_content = QWidget()
        self.claims_on_my_items_layout = QVBoxLayout(claims_on_items_content) # Layout for received claim cards
        self.claims_on_my_items_layout.setAlignment(Qt.AlignTop)
        self.claims_on_my_items_layout.setSpacing(10)
        self.claims_on_my_items_layout.setContentsMargins(8, 8, 8, 8)
        claims_on_items_scroll.setWidget(claims_on_items_content)
        claims_on_my_items_layout_outer.addWidget(claims_on_items_scroll)
        claims_management_layout.addWidget(claims_on_my_items_group, 1) # Stretch factor

        # My Submitted Claims (for Claimants)
        my_submitted_claims_group = QGroupBox("My Submitted Claims")
        my_submitted_claims_layout_outer = QVBoxLayout(my_submitted_claims_group)
        my_claims_scroll = QScrollArea()
        my_claims_scroll.setWidgetResizable(True)
        my_claims_scroll.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 5px; background-color: #f8f8f8;")
        my_claims_content = QWidget()
        self.my_claims_layout = QVBoxLayout(my_claims_content) # Layout for submitted claim cards
        self.my_claims_layout.setAlignment(Qt.AlignTop)
        self.my_claims_layout.setSpacing(10)
        self.my_claims_layout.setContentsMargins(8, 8, 8, 8)
        my_claims_scroll.setWidget(my_claims_content)
        my_submitted_claims_layout_outer.addWidget(my_claims_scroll)
        claims_management_layout.addWidget(my_submitted_claims_group, 1) # Stretch factor

        splitter_layout.addWidget(claims_management_group)


        self.stacked_widget.addWidget(profile_widget)


    # --- Event Handling Methods ---
    def handle_login(self):
        """Handle user login"""
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot log in.", is_error=True)
             return

        email = self.login_email.text().strip()
        password = self.login_password.text().strip()

        if not email or not password:
            QMessageBox.warning(self, "Login Failed", "Please enter both email and password.")
            return
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            QMessageBox.warning(self, "Login Failed", "Please enter a valid email address.")
            return

        success, result = login_user(email, password)

        if success:
            self.current_user = result # Store {'id': ?, 'username': ?, 'email': ?}
            self.welcome_label.setText(f"Welcome back, <b>{self.current_user['username']}</b>!")
            self.stacked_widget.setCurrentIndex(2)  # Go to home page
            self.login_email.clear()
            self.login_password.clear()
            self.show_flash_message(f"Logged in as {self.current_user['username']}.")
        else:
            QMessageBox.warning(self, "Login Failed", str(result))
            self.current_user = None


    def handle_register(self):
        """Handle user registration"""
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot register.", is_error=True)
             return

        username = self.register_username.text().strip()
        email = self.register_email.text().strip()
        password = self.register_password.text().strip()
        confirm_password = self.register_confirm_password.text().strip()

        if not username or not email or not password or not confirm_password:
            QMessageBox.warning(self, "Registration Failed", "Please fill in all fields.")
            return
        if password != confirm_password:
            QMessageBox.warning(self, "Registration Failed", "Passwords do not match.")
            return
        if len(password) < 6:
            QMessageBox.warning(self, "Registration Failed", "Password must be at least 6 characters long.")
            return
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            QMessageBox.warning(self, "Registration Failed", "Please enter a valid email address.")
            return

        success, message = register_user(username, email, password)

        if success:
            QMessageBox.information(self, "Registration Successful",
                                   "Account created! You can now log in.")
            self.stacked_widget.setCurrentIndex(0)  # Back to login page
            self.register_username.clear()
            self.register_email.clear()
            self.register_password.clear()
            self.register_confirm_password.clear()
        else:
            QMessageBox.warning(self, "Registration Failed", message)


    def handle_logout(self):
        """Handle user logout"""
        reply = QMessageBox.question(self, 'Confirm Logout', 'Are you sure you want to log out?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logged_out_user = self.current_user['username'] if self.current_user else "User"
            self.current_user = None
            self.stacked_widget.setCurrentIndex(0) # Back to login page
            # Clear sensitive fields
            self.login_email.clear()
            self.login_password.clear()
            self.item_title.clear(); self.item_location.clear(); self.item_description.clear()
            self.image_preview_label.clear(); self.selected_image_path = None
            self.profile_username_label.setText("Username: "); self.profile_email_label.setText("Email: ")
            self.clear_layout(self.user_items_layout)
            self.clear_layout(self.claims_on_my_items_layout)
            self.clear_layout(self.my_claims_layout)
            self.show_flash_message(f"{logged_out_user} logged out successfully.")


    def show_post_item_page(self, status):
        """Show the post item page with specified status (lost/found)"""
        if not self.current_user:
             self.show_flash_message("Please log in to post items.", is_error=True)
             self.stacked_widget.setCurrentIndex(0) # Redirect to login
             return

        self.current_item_status = status
        button_style_base = "QPushButton { color: white; padding: 14px; border-radius: 5px; font-weight: bold; font-size: 16px; border: none; } QPushButton:hover { filter: brightness(110%); }"
        if status == "lost":
            self.post_title_label.setText("Post Lost Item")
            self.submit_item_button.setStyleSheet(button_style_base + "QPushButton { background-color: #ffb74d; }")
            self.item_date.setToolTip("Date the item was lost")
        else: # Found
            self.post_title_label.setText("Post Found Item")
            self.submit_item_button.setStyleSheet(button_style_base + "QPushButton { background-color: #81c784; }")
            self.item_date.setToolTip("Date the item was found")

        # Clear form fields
        self.item_title.clear(); self.item_category.setCurrentIndex(0); self.item_location.clear()
        self.item_date.setDate(QDate.currentDate()); self.item_description.clear()
        self.selected_image_path = None
        self.image_preview_label.clear(); self.image_preview_label.setText("No Image\nSelected")

        self.stacked_widget.setCurrentIndex(3)


    def handle_post_item(self):
        """Handle posting a new item, including the image"""
        if not self.current_user:
            self.show_flash_message("You must be logged in to post an item.", is_error=True)
            return
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot post item.", is_error=True)
             return

        title = self.item_title.text().strip()
        category = self.item_category.currentText()
        location = self.item_location.text().strip()
        date = self.item_date.date().toString("yyyy-MM-dd")
        description = self.item_description.toPlainText().strip()

        if not title or not location or not description:
            QMessageBox.warning(self, "Submission Error", "Please fill in Title, Location, and Description.")
            return
        # Let's make image optional for now? No, keep required as per original logic.
        if not self.selected_image_path:
            QMessageBox.warning(self, "Submission Error", "Please select an image for the item.")
            return

        # Read image data
        image_data = None
        try:
            with open(self.selected_image_path, 'rb') as f:
                image_data = f.read()
            if len(image_data) > 16 * 1024 * 1024:
                 QMessageBox.warning(self, "Image Error", "Selected image is too large (max 16MB).")
                 return
        except Exception as e:
            QMessageBox.warning(self, "Image Error", f"Could not read image file: {e}")
            return # Stop submission if image is invalid

        # Save the item
        success, message = save_item(
            self.current_user['id'], title, category, location, date,
            self.current_item_status, description, image_data
        )

        if success:
            self.show_flash_message(message)
            self.show_view_items_page() # Go to view items page
        else:
            QMessageBox.critical(self, "Error Saving Item", message)


    def show_view_items_page(self):
        """Show the page with all non-recovered items, refreshing filters"""
        if not self.current_user:
             self.show_flash_message("Please log in to view items.", is_error=True)
             self.stacked_widget.setCurrentIndex(0)
             return
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot load items.", is_error=True)
             # Allow showing the page, but loading will fail
             pass

        # Update filter comboboxes 
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

        self.stacked_widget.setCurrentIndex(4) # Switch page first
        # Load items based on current filters (excluding recovered)
        self.load_all_items(
             self.category_filter.currentText(),
             self.location_filter.currentText(),
             include_recovered=False # Explicitly exclude recovered
        ) 


    def apply_item_filters(self):
        """Apply filters to the items list"""
        if not self.current_user: return
        self.load_all_items(
            self.category_filter.currentText(),
            self.location_filter.currentText(),
            include_recovered=False # Exclude recovered on general view
        )

    def reset_item_filters(self):
        """Reset filters to default and reload items"""
        if not self.current_user: return
        self.category_filter.setCurrentIndex(0)
        self.location_filter.setCurrentIndex(0)
        self.load_all_items(include_recovered=False) # Exclude recovered


    def load_all_items(self, filter_category=None, filter_location=None, include_recovered=False):
        """Load and display items with optional filtering and recovery status"""
        if not self.databases_connected: return # Don't try if DB offline
        self.clear_layout(self.items_list_layout) 

        loading_label = QLabel("Loading items...") # Add loading indicator
        loading_label.setAlignment(Qt.AlignCenter); loading_label.setStyleSheet("color: #888; margin: 30px 0;")
        self.items_list_layout.addWidget(loading_label)
        QApplication.processEvents()

        items = get_all_items(filter_category, filter_location, include_recovered)
        self.clear_layout(self.items_list_layout) # Remove loading label

        if not items:
            no_items_label = QLabel("No items found matching your criteria.")
            no_items_label.setAlignment(Qt.AlignCenter); no_items_label.setStyleSheet("color: #666; margin: 30px 0;")
            self.items_list_layout.addWidget(no_items_label)
            return

        for item in items:
            # Pass the item dictionary directly
            item_widget = self.create_item_widget(item, context='view_all')
            self.items_list_layout.addWidget(item_widget)


    def show_profile_page(self):
        """Show the user profile page, including items and claims sections"""
        if not self.current_user:
            self.show_flash_message("Please log in to view your profile.", is_error=True)
            self.stacked_widget.setCurrentIndex(0)
            return
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot load profile data.", is_error=True)
             # Allow showing page but loading will fail
             pass

        # Update user info display
        self.profile_username_label.setText(f"Username: <b>{self.current_user['username']}</b>")
        self.profile_email_label.setText(f"Email: {self.current_user['email']}")

        self.stacked_widget.setCurrentIndex(5) # Switch page first

        # Load user's items and claims (both received and submitted)
        self.load_user_items()
        self.load_claims_on_my_items()
        self.load_my_submitted_claims()

    def load_user_items(self):
        """Load items posted by the current user for the profile page"""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.user_items_layout)

        loading_label = QLabel("Loading your items..."); loading_label.setAlignment(Qt.AlignCenter); loading_label.setStyleSheet("color: #888; margin: 20px 0;")
        self.user_items_layout.addWidget(loading_label)
        QApplication.processEvents()

        items = get_user_items(self.current_user['id'])
        self.clear_layout(self.user_items_layout)

        if not items:
            no_items_label = QLabel("You haven't posted any items yet."); no_items_label.setAlignment(Qt.AlignCenter); no_items_label.setStyleSheet("color: #666; margin: 20px 0;")
            self.user_items_layout.addWidget(no_items_label)
            return

        for item in items:
             # Pass the item dictionary
            item_widget = self.create_item_widget(item, context='profile_own')
            self.user_items_layout.addWidget(item_widget)


    def load_claims_on_my_items(self):
        """Load claims made by others on items owned by the current user."""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.claims_on_my_items_layout)

        loading_label = QLabel("Loading received claims..."); loading_label.setAlignment(Qt.AlignCenter); loading_label.setStyleSheet("color: #888; margin: 15px 0;")
        self.claims_on_my_items_layout.addWidget(loading_label)
        QApplication.processEvents()

        # Need to get items owned by user first, then get claims for each item
        my_items = get_user_items(self.current_user['id']) # We might already have this? Let's refetch for simplicity.
        all_claims_on_my_items = []
        for item in my_items:
            # Only show claims for items that are NOT recovered yet
            if item.get('status') != 'recovered':
                claims_for_this_item = get_claims_for_item(item['id'])
                # Add item title to each claim dict for context
                for claim in claims_for_this_item:
                    claim['item_title'] = item['title']
                    all_claims_on_my_items.append(claim)

        # Sort claims (e.g., by date, or group by item) - simple date sort for now
        all_claims_on_my_items.sort(key=lambda x: x['claim_created_at'], reverse=True)

        self.clear_layout(self.claims_on_my_items_layout) # Remove loading

        if not all_claims_on_my_items:
            no_claims_label = QLabel("No pending claims on your items."); no_claims_label.setAlignment(Qt.AlignCenter); no_claims_label.setStyleSheet("color: #666; margin: 15px 0;")
            self.claims_on_my_items_layout.addWidget(no_claims_label)
            return

        for claim in all_claims_on_my_items:
             # Pass the claim dictionary
            claim_widget = self.create_claim_widget(claim, context='owner_view')
            self.claims_on_my_items_layout.addWidget(claim_widget)


    def load_my_submitted_claims(self):
        """Load claims submitted by the current user."""
        if not self.current_user or not self.databases_connected: return
        self.clear_layout(self.my_claims_layout)

        loading_label = QLabel("Loading your submitted claims..."); loading_label.setAlignment(Qt.AlignCenter); loading_label.setStyleSheet("color: #888; margin: 15px 0;")
        self.my_claims_layout.addWidget(loading_label)
        QApplication.processEvents()

        my_claims = get_claims_by_claimant(self.current_user['id'])
        self.clear_layout(self.my_claims_layout)

        if not my_claims:
            no_claims_label = QLabel("You haven't submitted any claims yet."); no_claims_label.setAlignment(Qt.AlignCenter); no_claims_label.setStyleSheet("color: #666; margin: 15px 0;")
            self.my_claims_layout.addWidget(no_claims_label)
            return

        for claim in my_claims:
             # Pass the claim dictionary
            claim_widget = self.create_claim_widget(claim, context='claimant_view')
            self.my_claims_layout.addWidget(claim_widget)


    def create_item_widget(self, item_data, context='view_all'):
        """Creates a widget for displaying an item.
           Context can be 'view_all', 'profile_own'.
           Includes image, details, and context-specific buttons.
           Expects item_data dictionary.
        """
        item_widget = QWidget()
        item_widget.setStyleSheet("background-color: #ffffff; border-radius: 8px; border: 1px solid #e0e0e0; padding: 0px;")

        card_layout = QHBoxLayout(item_widget)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)

        # --- Image Area ---
        image_label = QLabel()
        img_size = 100 # Image size
        image_label.setFixedSize(img_size, img_size)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setStyleSheet("background-color: #f0f0f0; border-radius: 5px; border: 1px solid #ddd;")

        pixmap = self.load_pixmap_from_data(item_data.get('image_data'))
        if pixmap:
            scaled_pixmap = pixmap.scaled(image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            image_label.setToolTip("Item Image")
        else:
            image_label.setText("No Image")
            image_label.setToolTip("No image provided")

        card_layout.addWidget(image_label, 0)

        # --- Details Area ---
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(5) # Reduced spacing

        # Top line: Title and Status
        top_line_layout = QHBoxLayout()
        title_text = item_data.get('title', 'No Title')
        title_label = QLabel(f"<b>{title_text}</b>")
        title_label.setStyleSheet(f"color: {ACCENT_COLOR}; font-size: 14px;")
        title_label.setWordWrap(True)
        title_label.setToolTip(title_text)

        item_status = item_data.get('status', 'unknown')
        status_label = QLabel(item_status.upper())
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        status_style = "color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;"
        if item_status == 'lost': status_label.setStyleSheet(f"background-color: #ffb74d; {status_style}")
        elif item_status == 'found': status_label.setStyleSheet(f"background-color: #81c784; {status_style}")
        elif item_status == 'recovered': status_label.setStyleSheet(f"background-color: #78909c; {status_style}") # Grey for recovered
        else: status_label.setStyleSheet(f"background-color: #bdbdbd; {status_style}")

        top_line_layout.addWidget(title_label)
        top_line_layout.addStretch()
        top_line_layout.addWidget(status_label)
        details_layout.addLayout(top_line_layout)

        # Middle section: Other details
        details_form = QFormLayout()
        details_form.setContentsMargins(0, 5, 0, 0)
        details_form.setSpacing(4)
        details_form.setLabelAlignment(Qt.AlignLeft)
        details_form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        def create_detail_label(text):
            lbl = QLabel(str(text)) # Ensure text is string
            lbl.setStyleSheet("font-size: 12px; color: #444;")
            lbl.setWordWrap(True)
            return lbl

        # Show owner only if not on own profile page
        if context != 'profile_own' and 'owner_username' in item_data:
            details_form.addRow(QLabel("<b>Posted by:</b>"), create_detail_label(item_data['owner_username']))
        details_form.addRow(QLabel("<b>Category:</b>"), create_detail_label(item_data.get('category', 'N/A')))
        details_form.addRow(QLabel("<b>Location:</b>"), create_detail_label(item_data.get('location', 'N/A')))
        details_form.addRow(QLabel("<b>Date:</b>"), create_detail_label(item_data.get('date', 'N/A')))
        details_layout.addLayout(details_form)

        # Description
        desc_text = item_data.get('description', 'No description.')
        description_label = QLabel(desc_text)
        description_label.setWordWrap(True)
        description_label.setStyleSheet("font-size: 12px; color: #555; margin-top: 5px;")
        description_label.setAlignment(Qt.AlignTop)
        details_layout.addWidget(description_label, 1) # Give description stretch factor

        # --- Action Button Area ---
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 8, 0, 0) # Add top margin
        button_layout.addStretch() # Push buttons to the right

        # --- *** UPDATED CONDITION FOR CLAIM BUTTON *** ---
        # Check if user is logged in before checking ID
        user_logged_in = self.current_user is not None
        current_user_id = self.current_user['id'] if user_logged_in else -1 # Use -1 if not logged in

        is_claimable = ( user_logged_in and # Must be logged in
                         context == 'view_all' and # Must be on the general view page
                         item_data.get('status') in ['found', 'lost'] and # **** ALLOW CLAIMING 'found' OR 'lost' ITEMS ****
                         item_data.get('user_id') != current_user_id ) # Cannot claim own item

        if is_claimable:
            claim_button = QPushButton(QIcon.fromTheme("mail-mark-unread"), " Claim This Item")
            claim_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: white; padding: 6px 12px; border-radius: 4px; font-size: 12px; font-weight: bold; border:none;")
            claim_button.setCursor(Qt.PointingHandCursor)
            # Use lambda to pass item_id to the handler
            claim_button.clicked.connect(lambda checked, iid=item_data['id']: self.handle_claim_button_click(iid))
            button_layout.addWidget(claim_button)

        # Add button layout to details section if it contains buttons
        if button_layout.count() > 1: # If more than just the stretch item
            details_layout.addLayout(button_layout)
        else:
            # If no buttons, add a small spacer or stretch to maintain layout consistency
            details_layout.addSpacerItem(QSpacerItem(0, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))


        card_layout.addWidget(details_widget, 1) # Add details (stretch factor 1)
        return item_widget


    def create_claim_widget(self, claim_data, context='owner_view'):
        """Creates a widget for displaying a claim.
           Context: 'owner_view' or 'claimant_view'.
           Includes claim details, evidence preview, and context-specific buttons.
           Expects claim_data dictionary.
        """
        claim_widget = QWidget()
        base_style = "border-radius: 6px; border: 1px solid #ccc; padding: 10px;"
        # Differentiate background slightly based on status?
        claim_status = claim_data.get('claim_status', 'pending')
        bg_color = "#ffffff" # Default white for pending
        if claim_status == 'accepted': bg_color = "#e8f5e9" # Light green
        elif claim_status == 'rejected': bg_color = "#ffebee" # Light red

        claim_widget.setStyleSheet(f"background-color: {bg_color}; {base_style}")

        main_layout = QVBoxLayout(claim_widget)
        main_layout.setSpacing(8)

        # Top Line: Item Info (if claimant view) or Claimant Info (if owner view) + Status
        top_line_layout = QHBoxLayout()
        top_line_layout.setContentsMargins(0,0,0,0)

        info_label = QLabel()
        info_label.setStyleSheet("font-size: 13px;")
        info_label.setWordWrap(True)
        if context == 'claimant_view':
             item_title = claim_data.get('item_title', 'Unknown Item')
             item_status_for_claim = claim_data.get('item_status', '?')
             info_label.setText(f"Your claim on: <b>{item_title}</b> (Item Status: {item_status_for_claim.upper()})")
             info_label.setToolTip(f"Claim on item ID: {claim_data.get('item_id')}")
        else: # owner_view
             claimant_name = claim_data.get('claimant_username', 'Unknown User')
             item_title_for_owner = claim_data.get('item_title', 'Your Item') # Added in load_claims_on_my_items
             info_label.setText(f"Claim by <b>{claimant_name}</b> on: <i>{item_title_for_owner}</i>")
             info_label.setToolTip(f"Claim ID: {claim_data.get('claim_id')}, Claimant ID: {claim_data.get('claimant_id')}")


        status_label = QLabel(claim_status.upper())
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        status_style = "color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;"
        if claim_status == 'pending': status_label.setStyleSheet(f"background-color: #ffc107; {status_style}") # Amber
        elif claim_status == 'accepted': status_label.setStyleSheet(f"background-color: #4caf50; {status_style}") # Green
        elif claim_status == 'rejected': status_label.setStyleSheet(f"background-color: #f44336; {status_style}") # Red
        else: status_label.setStyleSheet(f"background-color: #bdbdbd; {status_style}")

        top_line_layout.addWidget(info_label, 1) # Give label stretch
        top_line_layout.addWidget(status_label)
        main_layout.addLayout(top_line_layout)

        # Claim Reason
        reason_label = QLabel(f"<b>Reason:</b> {claim_data.get('reason', 'No reason provided.')}")
        reason_label.setStyleSheet("font-size: 12px; color: #333;")
        reason_label.setWordWrap(True)
        main_layout.addWidget(reason_label)

        # Claim Date
        created_at_raw = claim_data.get('claim_created_at', '')
        created_at_str = str(created_at_raw).split('.')[0] if created_at_raw else 'Unknown Date' # Format nicely
        date_label = QLabel(f"<i>Submitted: {created_at_str}</i>")
        date_label.setStyleSheet("font-size: 11px; color: #666;")
        main_layout.addWidget(date_label)


        # Evidence Image (if available) & Action Buttons
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
                  evidence_img_label.setToolTip("Evidence Image Provided")
             else:
                  evidence_img_label.setText("Invalid\nEvidence")
                  evidence_img_label.setToolTip("Could not load evidence image")
             bottom_layout.addWidget(evidence_img_label) # Add evidence preview
        else:
             no_evidence_label = QLabel("<i>No evidence provided</i>")
             no_evidence_label.setStyleSheet("font-size: 11px; color: #888;")
             bottom_layout.addWidget(no_evidence_label)


        bottom_layout.addStretch() # Push buttons right

        # Action Buttons (Accept/Reject for owner on pending claims)
        if context == 'owner_view' and claim_status == 'pending':
            accept_button = QPushButton(QIcon.fromTheme("dialog-ok-apply"), " Accept")
            accept_button.setStyleSheet("background-color: #4caf50; color: white; padding: 5px 10px; border-radius: 4px; font-size: 11px; border: none;")
            accept_button.setCursor(Qt.PointingHandCursor)
            accept_button.clicked.connect(lambda checked, cid=claim_data['claim_id'], iid=claim_data['item_id']: self.handle_accept_claim(cid, iid))
            bottom_layout.addWidget(accept_button)

            reject_button = QPushButton(QIcon.fromTheme("dialog-cancel"), " Reject")
            reject_button.setStyleSheet("background-color: #f44336; color: white; padding: 5px 10px; border-radius: 4px; font-size: 11px; border: none;")
            reject_button.setCursor(Qt.PointingHandCursor)
            reject_button.clicked.connect(lambda checked, cid=claim_data['claim_id']: self.handle_reject_claim(cid))
            bottom_layout.addWidget(reject_button)

        main_layout.addLayout(bottom_layout)

        return claim_widget


    def handle_claim_button_click(self, item_id):
        """Opens the claim dialog when 'Claim This Item' is clicked."""
        if not self.current_user:
             self.show_flash_message("Please log in to submit a claim.", is_error=True)
             return
        if not self.databases_connected:
             self.show_flash_message("Database connection error. Cannot submit claim.", is_error=True)
             return

        # Check if user has already claimed this item (optional but good)
        # claims_on_this = get_claims_for_item(item_id)
        # already_claimed = any(c['claimant_id'] == self.current_user['id'] for c in claims_on_this)
        # if already_claimed:
        #      QMessageBox.information(self, "Already Claimed", "You have already submitted a claim for this item.")
        #      return

        dialog = ClaimDialog(item_id, self)
        if dialog.exec_() == QDialog.Accepted:
            claim_data = dialog.get_claim_data()
            if claim_data:
                reason, evidence_data = claim_data
                success, message = submit_claim(item_id, self.current_user['id'], reason, evidence_data)
                if success:
                    self.show_flash_message(message)
                    # Optionally, refresh the view or profile page if needed
                    if self.stacked_widget.currentIndex() == 5: # If on profile page
                        self.load_my_submitted_claims() # Refresh submitted claims list
                else:
                    self.show_flash_message(message, is_error=True)
            else:
                # This case handled by dialog validation, but good to have
                self.show_flash_message("Claim submission cancelled or failed validation.", is_error=True)


    def handle_accept_claim(self, claim_id, item_id):
        """Handles the 'Accept' button click for a claim."""
        reply = QMessageBox.question(self, 'Confirm Acceptance',
                                     f"Are you sure you want to accept claim {claim_id} for item {item_id}?\n"
                                     "This will mark the item as 'recovered' and reject other pending claims.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
             if not self.databases_connected:
                  self.show_flash_message("Database error. Cannot accept claim.", is_error=True)
                  return
             success, message = accept_claim(claim_id, item_id)
             if success:
                  self.show_flash_message(message)
                  # Refresh the profile page views
                  self.load_user_items()
                  self.load_claims_on_my_items()
                  self.load_my_submitted_claims()
             else:
                  self.show_flash_message(f"Failed to accept claim: {message}", is_error=True)


    def handle_reject_claim(self, claim_id):
        """Handles the 'Reject' button click for a claim."""
        reply = QMessageBox.question(self, 'Confirm Rejection',
                                     f"Are you sure you want to reject claim {claim_id}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
             if not self.databases_connected:
                  self.show_flash_message("Database error. Cannot reject claim.", is_error=True)
                  return
             success, message = reject_claim(claim_id)
             if success:
                  self.show_flash_message(f"Claim {claim_id} rejected.")
                  # Refresh the claims on my items view
                  self.load_claims_on_my_items()
                  self.load_my_submitted_claims() # Also refresh claimant view if they are the same user
             else:
                  self.show_flash_message(f"Failed to reject claim: {message}", is_error=True)


    def load_pixmap_from_data(self, image_data):
        """Safely load a QPixmap from binary data."""
        if not image_data:
            return None
        try:
            pixmap = QPixmap()
            # Use QBuffer and QIODevice to load from bytes
            buffer = QBuffer()
            buffer.setData(bytes(image_data)) # Ensure it's bytes
            buffer.open(QIODevice.ReadOnly)
            loaded = pixmap.loadFromData(buffer.readAll()) # Read data from buffer
            buffer.close()
            return pixmap if loaded else None
        except Exception as e:
            print(f"Error loading pixmap from data: {e}")
            return None

    def clear_layout(self, layout):
        """Clear all widgets from a layout recursively"""
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

# --- Main application entry point ---
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
                print("MySQL connection closed.")
            except Exception as e:
                 print(f"Error closing MySQL connection: {e}")
        if mongo_client:
            try:
                mongo_client.close()
                print("MongoDB connection closed.")
            except Exception as e:
                 print(f"Error closing MongoDB connection: {e}")

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()