-- Echo-Chat: purge live room chat history while keeping group and private-message rows.
-- Review the WHERE clause before running on production.
-- Group messages are stored with room keys like g:<group_id> and are excluded here.

BEGIN;

DELETE FROM messages
WHERE receiver IS NULL
  AND room IS NOT NULL
  AND room NOT LIKE 'g:%';

COMMIT;
