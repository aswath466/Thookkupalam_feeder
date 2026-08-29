-- Adds the columns needed for self-service operator registration
-- (mirrors the Erattayar app's operators table). Safe to run once;
-- MySQL doesn't support "ADD COLUMN IF NOT EXISTS" cleanly pre-8.0.29,
-- so if a column already exists just skip that line.

ALTER TABLE operators
    ADD COLUMN email VARCHAR(150) DEFAULT NULL AFTER display_name,
    ADD COLUMN approval_token VARCHAR(64) DEFAULT NULL AFTER status;

-- 'status' is currently ENUM('pending','active') which already covers
-- the registration flow (new accounts insert as 'pending').
