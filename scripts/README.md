# Postgres repair scripts

These SQL helpers are for local development and repair work.

## Included scripts

- `pg_fix_ownership.sql` — transfer table ownership to the role your app is using
- `pg_refresh_collation.sql` — refresh collation metadata after a system or Postgres upgrade when needed
- `pg_find_duplicate_emails.sql` — locate duplicate user emails
- `pg_dedupe_emails_set_null.sql` — keep one email and null the rest
- `pg_dedupe_emails_keep_lowest_id.sql` — preserve the lowest-id row as the keeper
- `pg_purge_room_history.sql` — targeted room-history cleanup helper

## Typical ownership repair

```bash
sudo -u postgres psql -d YOUR_DB -v new_owner=YOUR_ROLE -f scripts/pg_fix_ownership.sql
```

## Duplicate-email investigation

```bash
sudo -u postgres psql -d YOUR_DB -f scripts/pg_find_duplicate_emails.sql
```

## Duplicate-email cleanup

```bash
sudo -u postgres psql -d YOUR_DB -f scripts/pg_dedupe_emails_set_null.sql
```

## Caution

Run these only against the intended database. Some of them are destructive by design.
