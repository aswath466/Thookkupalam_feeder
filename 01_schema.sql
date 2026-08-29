-- Thookkupalam Section: 11kV Feeder Monitoring System
-- MySQL schema (corrected to match app.py / feeder_trace.py / diagram_svg.html
-- field names — the original schema.sql used from_node_id/to_node_id and
-- feeders.color, but the app code expects node_a_id/node_b_id and
-- feeders.color_hex. This version is the one actually wired up to the app.)

CREATE DATABASE IF NOT EXISTS thookkupalam_feeder;
USE thookkupalam_feeder;

-- Nodes: every point on the SLD (transformer, junction, switch/AB point, source)
CREATE TABLE IF NOT EXISTS nodes (
    id INT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    x INT NOT NULL,
    y INT NOT NULL,
    type ENUM('junction', 'transformer', 'switch', 'source') NOT NULL DEFAULT 'junction',
    label_offset_x INT DEFAULT 0,
    label_offset_y INT DEFAULT 0,
    transformer_no INT DEFAULT NULL,
    kva DECIMAL(10,2) DEFAULT NULL
);

-- Edges: connections/wires between nodes. Some edges represent AB switch legs.
-- Column names match what app.py / feeder_trace.py / diagram_svg.html read:
-- node_a_id, node_b_id (not from_node_id/to_node_id).
CREATE TABLE IF NOT EXISTS edges (
    id INT PRIMARY KEY AUTO_INCREMENT,
    node_a_id INT NOT NULL,
    node_b_id INT NOT NULL,
    is_switch BOOLEAN DEFAULT FALSE,
    switch_state ENUM('open', 'closed') DEFAULT 'closed',
    label VARCHAR(120) DEFAULT NULL,
    FOREIGN KEY (node_a_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (node_b_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Feeders. Column is color_hex (not color) to match diagram_svg.html /
-- index.html, which read f.color_hex directly.
CREATE TABLE IF NOT EXISTS feeders (
    id INT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    color_hex VARCHAR(20) NOT NULL DEFAULT '#888888'
);

-- Feeder source nodes: BFS coloring starts here. Supports multiple entry
-- points per feeder (needed for feeder id 2, which has two physical sources:
-- node 108 and node 388 — see README). feeder_trace.py now reads from this
-- table instead of a single source_node_id column.
CREATE TABLE IF NOT EXISTS feeder_sources (
    id INT PRIMARY KEY AUTO_INCREMENT,
    feeder_id INT NOT NULL,
    node_id INT NOT NULL,
    FOREIGN KEY (feeder_id) REFERENCES feeders(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Ledger: actual transformer capacities (populate from field data / Excel later)
CREATE TABLE IF NOT EXISTS ledger (
    id INT PRIMARY KEY AUTO_INCREMENT,
    transformer_node_id INT NOT NULL,
    feeder_id INT,
    capacity_kva DECIMAL(10,2),
    remarks VARCHAR(255),
    FOREIGN KEY (transformer_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (feeder_id) REFERENCES feeders(id) ON DELETE SET NULL
);
