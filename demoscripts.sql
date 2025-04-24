-- Fetch a few rows from a smaller table
SELECT * FROM demo_1k_seq LIMIT 10;

-- Fetch a specific row using the Primary Key (should be fast due to index)
SELECT id, value FROM demo_1m_seq WHERE id = 789123;

-- Fetch rows based on the non-indexed 'value' column (might be slower on large tables)
SELECT id, value FROM demo_100k_seq WHERE value = 50;

-- Fetch rows using a range query on the PK (should be efficient)
SELECT id FROM demo_100k_seq WHERE id > 99980;

-- Combine filters using AND (const table value is always 1)
SELECT id, value FROM demo_1m_const WHERE id < 100 AND value = 1;

-- Combine filters using OR (should return rows from start and end)
SELECT id, value FROM demo_1m_seq WHERE id < 5 OR id > 999995;

-- Filter using inequality
SELECT id FROM demo_1k_seq WHERE value != 10 LIMIT 10;

-- Count all rows in the largest table (requires full scan)
SELECT COUNT(*) FROM demo_1m_seq;

-- Calculate multiple aggregates on the largest table
SELECT COUNT(*), MIN(value), MAX(value), SUM(value), AVG(value) FROM demo_1m_seq;

-- Group by the constant value (should result in one group)
SELECT value, COUNT(*) FROM demo_1m_const GROUP BY value;

-- Group by value on the sequential table (each value is unique, so 1M groups if no WHERE)
-- Let's filter first to make it manageable
SELECT value, COUNT(*) FROM demo_1m_seq WHERE id < 10 GROUP BY value;

-- Group by a calculated value and filter groups with HAVING
-- Find groups based on the last digit of 'value' that have almost all members
SELECT value % 10 AS last_digit, COUNT(*)
FROM demo_100k_seq
GROUP BY last_digit
HAVING COUNT(*) > 9995;

-- Get the highest IDs from a large table (should use index effectively)
SELECT id FROM demo_1m_seq ORDER BY id DESC LIMIT 10;

-- Get the rows with the highest values (value is same as id here)
SELECT id, value FROM demo_100k_seq ORDER BY value DESC LIMIT 5;

-- Order by the constant value (order might be arbitrary after value)
SELECT id, value FROM demo_1k_const ORDER BY value ASC, id DESC LIMIT 10;


-- Join two smaller tables on their primary key (indexed join)
SELECT t1.id, t1.value, t2.value
FROM demo_1k_seq AS t1, demo_1k_const AS t2
WHERE t1.id = t2.id
LIMIT 10;

-- Join a small table with a large table on PK
SELECT COUNT(*)
FROM demo_1k_seq AS t1k, demo_1m_seq AS t1m
WHERE t1k.id = t1m.id;

-- Join two large tables on the 'value' column (non-indexed join, potentially slow)
-- Using the 'const' tables where value is always 1 - this will create a huge cross product conceptually
-- Limit is essential here to avoid printing millions of rows if it succeeds!
SELECT t1.id, t2.id
FROM demo_100k_const AS t1, demo_1m_const AS t2
WHERE t1.value = t2.value
LIMIT 10;

-- Join sequential tables on value (value=id, so same as joining on id)
SELECT COUNT(*)
FROM demo_100k_seq AS t1, demo_1m_seq AS t2
WHERE t1.value = t2.value;

-- Join a sequential table with a const table on 'value'
-- This finds rows in demo_100k_seq where value=1 (only the first row)
SELECT t_seq.id, t_seq.value, t_const.id
FROM demo_100k_seq AS t_seq, demo_100k_const AS t_const
WHERE t_seq.value = t_const.value;


-- Insert multiple new rows
INSERT INTO demo_1k_const (id, value) VALUES (1001, 1), (1002, 1);

-- Verify insertion
SELECT * FROM demo_1k_const WHERE id > 1000;

-- Update one of the new rows
UPDATE demo_1k_const SET value = 1001 WHERE id = 1001;

-- Verify update
SELECT * FROM demo_1k_const WHERE id = 1001;

-- Delete the added rows
DELETE FROM demo_1k_const WHERE id > 1000;

-- Verify deletion (count should be back to 1000)
SELECT COUNT(*) FROM demo_1k_const;