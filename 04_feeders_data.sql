USE thookkupalam_feeder;

INSERT INTO feeders (id, name, color_hex) VALUES
(2, 'Pambadumpara Feeder', '#2a9d8f'),
(3, 'Amayar Feeder (Vandanmedu SS)', '#f4a261'),
(4, 'Kattapana Feeder', '#457b9d'),
(5, 'Town Feeder', '#8338ec')
ON DUPLICATE KEY UPDATE name=VALUES(name), color_hex=VALUES(color_hex);

DELETE FROM feeder_sources;
INSERT INTO feeder_sources (feeder_id, node_id) VALUES
(2, 108),
(2, 388),
(3, 244),
(4, 346),
(5, 1);
