create database tawdrlik_DB;
use tawdrlik_DB;

CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(64) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
 CREATE TABLE IF NOT EXISTS items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                category VARCHAR(100),
                location VARCHAR(255),
                date DATE,
                status ENUM('lost', 'found', 'recovered') NOT NULL DEFAULT 'found',
                description TEXT,
                mongo_id VARCHAR(24) NULL, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
            
 CREATE TABLE IF NOT EXISTS claims (
                id INT AUTO_INCREMENT PRIMARY KEY,
                item_id INT NOT NULL,
                claimant_id INT NOT NULL,
                reason TEXT NOT NULL,
                status ENUM('pending', 'accepted', 'rejected') NOT NULL DEFAULT 'pending',
                mongo_detail_id VARCHAR(24) NULL, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (claimant_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
select * from items;
select * from claims;