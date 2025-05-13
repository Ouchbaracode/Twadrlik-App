CREATE DATABASE IF NOT EXISTS tawdrlikDB; 
USE tawdrlikDB;

-- Table pour les utilisateurs
CREATE TABLE IF NOT EXISTS utilisateurs (
    id_utilisateur INT AUTO_INCREMENT PRIMARY KEY,
    nom_utilisateur VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,        
    mot_de_passe VARCHAR(64) NOT NULL,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table pour les objets perdus/trouvés
CREATE TABLE IF NOT EXISTS objets (
    id_objet INT AUTO_INCREMENT PRIMARY KEY,
    id_utilisateur_proprietaire INT NOT NULL,
    titre VARCHAR(255) NOT NULL,
    categorie VARCHAR(100),
    lieu VARCHAR(255),
    date_evenement DATE, 
    statut_objet ENUM('lost', 'found', 'recovered') NOT NULL DEFAULT 'found', 
    description_meta TEXT,
    id_mongo_details VARCHAR(24) NULL, -- Lien vers les détails MongoDB (image, etc.)
    date_signalement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_objets_utilisateurs FOREIGN KEY (id_utilisateur_proprietaire) REFERENCES utilisateurs(id_utilisateur) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table pour les réclamations sur les objets
CREATE TABLE IF NOT EXISTS reclamations (
    id_reclamation INT AUTO_INCREMENT PRIMARY KEY,
    id_objet_reclame INT NOT NULL,
    id_utilisateur_reclamant INT NOT NULL,
    motif_reclamation TEXT NOT NULL,
    statut_reclamation ENUM('pending', 'accepted', 'rejected') NOT NULL DEFAULT 'pending', 
    id_mongo_preuve VARCHAR(24) NULL, -- Lien vers les détails de la preuve en MongoDB
    date_soumission_reclamation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reclamations_objets FOREIGN KEY (id_objet_reclame) REFERENCES objets(id_objet) ON DELETE CASCADE,
    CONSTRAINT fk_reclamations_utilisateurs FOREIGN KEY (id_utilisateur_reclamant) REFERENCES utilisateurs(id_utilisateur) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Les lignes SELECT * suivantes sont pour la vérification et ne font pas partie de la structure de création
-- Vous pouvez les exécuter après la création pour voir les tables vides (si la base est nouvelle)
SELECT * FROM objets;
-- SELECT * FROM reclamations;
SELECT * FROM utilisateurs; 