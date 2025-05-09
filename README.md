# Twadrlik - Lost & Found Application

**Developer:** Mohamed Ouchbara

**Idea:** Mohamed kharbouche


## Description

Twadrlik is a desktop application designed to help users report and find lost or found items. It provides a platform for users to register, post items they've lost or found (including descriptions and images), browse listed items, and submit claims for items they believe belong to them. The application utilizes a dual-database system: MySQL for structured data like user information and item metadata, and MongoDB for storing less structured data like item descriptions and images.

The application is available in two language versions: French (as the primary version in this setup) and English.

## Features

* User registration and login
* Post lost items with details (title, category, location, date, description, image)
* Post found items with details (title, category, location, date, description, image)
* View a list of all reported items (excluding those marked as 'recovered')
* Filter items by category and location
* View item details including images
* Submit claims for items, providing a reason and optional evidence image
* User profile page:
    * View items posted by the user
    * Manage claims received on the user's items (accept/reject)
    * View claims submitted by the user and their status

## Project Structure

The repository contains the following key files:

### French Version (Main application files):

* **Application Code:** `twadrlik fr.py` - The main Python script for the French version of the application.
* **Database Schema:** `db tawdrlik fr.sql` - SQL script to set up the MySQL database schema for the French version. 

### English Version:

* **Application Code:** `twadrlik en.py` - The main Python script for the English version of the application. 
* **Database Schema:** `db tawdrlik en.sql` - SQL script to set up the MySQL database schema for the English version. 

## Technologies Used

* **Programming Language:** Python
* **GUI Framework:** PyQt5
* **Databases:**
    * MySQL (for structured data like users, item metadata, claims)
    * MongoDB (for item details like descriptions and images)
* **Python Libraries:**
    * `mysql.connector` (for MySQL interaction)
    * `pymongo` (for MongoDB interaction)
    * `hashlib` (for password hashing)
    * `PyQt5`

## Setup and Installation

To run this application, you will need the following installed:

1.  **Python 3.x**
2.  **MySQL Server**
3.  **MongoDB Server**
4.  **Required Python Libraries:**
    Install them using pip:
    ```bash
    pip install PyQt5 mysql-connector-python pymongo
    ```

### Database Setup:

1.  **MySQL:**
    * Ensure your MySQL server is running.
    * Create a database.
        * For the French version (`twadrlik fr.py`), the application expects a database named `tawdrlik_DB` .
        * For the English version (`twadrlik en.py`), the application expects a database named `tawdrlikDB` 
    * Execute the appropriate SQL script (`db tawdrlik fr.sql` for French or `db tawdrlik en.sql` for English) in your MySQL environment to create the necessary tables.
    * Update the MySQL connection details (host, user, password, database name) in the `MYSQL_CONFIG` dictionary within the respective Python script (`twadrlik fr.py` or `twadrlik en.py`) if they differ from the defaults suggested by their original counterparts.

2.  **MongoDB:**
    * Ensure your MongoDB server is running.
    * The application will automatically create a database (e.g., `tawdrlikDB` as specified in `MONGODB_DB` variable in the Python scripts, this might need adjustment per version if the Python files were exact copies with just name changes) and collections (`items_detail`, `claims_detail`) when it first runs and saves data.
    * Update the MongoDB connection URI (`MONGODB_URI`) in the Python scripts if your MongoDB instance is not running on `mongodb://localhost:27017/`.

### Running the Application:

1.  Navigate to the directory containing the Python files.
2.  To run the French version:
    ```bash
    python "twadrlik fr.py"
    ```
3.  To run the English version:
    ```bash
    python "twadrlik en.py"
    ```

## Configuration

* **Database Credentials:**
    * MySQL: Modify the `MYSQL_CONFIG` dictionary in `twadrlik fr.py` (French) or `twadrlik en.py` (English) for your MySQL host, user, password, and database name, ensuring they match the intended database for that version.
    * MongoDB: Modify the `MONGODB_URI` and `MONGODB_DB` variables in the scripts if needed, ensuring consistency for each version.
* **Application Styling:** Colors and fonts can be adjusted via the global constants (`PRIMARY_COLOR`, `BACKGROUND_COLOR`, etc.) at the beginning of the Python scripts.

