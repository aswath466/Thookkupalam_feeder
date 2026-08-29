-- Operator accounts + audit logs, ported from the Erattayar
-- (git-feeder-monitor) app's operators / login_log / switch_log tables.
--
-- Differences from Erattayar's version, both deliberate:
--   1. No `email` / `approval_token` columns - this build doesn't include
--      the public /register + email-approval flow, only the admin-style
--      /create_operator bootstrap (see app.py). Easy to add later if you
--      want self-serve registration here too.
--   2. switch_log references a NODE id (switch_node_id), not an edge id -
--      Thookkupalam models each AB switch as its own node touched by two
--      edges, whereas Erattayar models a switch as a single edge. Logging
--      against the node keeps one row per physical switch-toggle instead
--      of two (one per leg).

USE thookkupalam_feeder;

CREATE TABLE IF NOT EXISTS operators (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    password_salt VARCHAR(36) NOT NULL,
    display_name VARCHAR(100) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending', 'active') NOT NULL DEFAULT 'active',
    role VARCHAR(20) NOT NULL DEFAULT 'viewer',
    UNIQUE KEY uq_operators_username (username)
);

CREATE TABLE IF NOT EXISTS login_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(100) NOT NULL,
    display_name VARCHAR(150) DEFAULT NULL,
    ip_address VARCHAR(45) DEFAULT NULL,
    login_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS switch_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    switch_node_id INT NOT NULL,
    new_state ENUM('open', 'closed') NOT NULL,
    operator VARCHAR(100) DEFAULT NULL,
    reason VARCHAR(255) DEFAULT NULL,
    switched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (switch_node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- No seed rows on purpose - the first account is created through
-- /create_operator, which only stays open while this table is empty
-- (see app.py). That avoids shipping a real username/password/hash in
-- source control.
