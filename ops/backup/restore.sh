#!/bin/sh
set -eu

umask 077

archive=/restore/plateos.dump.age
identity=/run/secrets/plateos_restore_identity
password_file=/run/secrets/plateos_restore_database_password
fifo="/tmp/plateos-restore-$$.fifo"
decrypt_pid=""

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$decrypt_pid" ] && kill -0 "$decrypt_pid" 2>/dev/null; then
        kill "$decrypt_pid" 2>/dev/null || true
        wait "$decrypt_pid" 2>/dev/null || true
    fi
    rm -f "$fifo"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "${PLATEOS_RESTORE_CONFIRM:-}" != "RESTORE_TO_ISOLATED_PLATEOS" ]; then
    echo "Restore confirmation is missing" >&2
    exit 1
fi
if [ "${PGHOST:-}" != "restore-db" ] || [ "${PGDATABASE:-}" != "plateos_restore" ]; then
    echo "Refusing to restore outside the isolated target" >&2
    exit 1
fi
if [ ! -r "$archive" ] || [ ! -r "$identity" ] || [ ! -r "$password_file" ]; then
    echo "Archive, restore identity, and database password must be readable" >&2
    exit 1
fi

export PGPASSWORD="$(cat "$password_file")"

# Inspect every database-local OID catalog rather than maintaining an object-type
# allowlist. PostgreSQL reserves OIDs below FirstNormalObjectId (16384) for the
# template's built-ins; normal created objects use that value or higher.
if ! psql --no-psqlrc --set=ON_ERROR_STOP=1 --command="
DO \$plateos_guard\$
DECLARE
    catalog_name regclass;
    catalog_count bigint;
BEGIN
    FOR catalog_name IN
        SELECT c.oid::regclass
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'pg_catalog'
          AND c.relkind IN ('r', 'p')
          AND NOT c.relisshared
          AND EXISTS (
              SELECT 1
              FROM pg_attribute AS a
              WHERE a.attrelid = c.oid
                AND a.attname = 'oid'
                AND NOT a.attisdropped
          )
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM %s WHERE oid >= 16384', catalog_name
        ) INTO catalog_count;
        IF catalog_count > 0 THEN
            RAISE EXCEPTION 'database contains created objects';
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_largeobject_metadata)
       OR EXISTS (
           SELECT 1 FROM pg_db_role_setting
           WHERE setdatabase = (
               SELECT oid FROM pg_database WHERE datname = current_database()
           )
       )
       OR EXISTS (SELECT 1 FROM pg_replication_origin)
    THEN
        RAISE EXCEPTION 'database contains non-OID state';
    END IF;
END
\$plateos_guard\$;
" >/dev/null 2>&1; then
    echo "Refusing to restore into a non-empty database" >&2
    exit 1
fi
mkfifo "$fifo"
age --decrypt --identity "$identity" "$archive" > "$fifo" &
decrypt_pid=$!

restore_ok=true
if ! pg_restore \
    --clean \
    --if-exists \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --dbname="$PGDATABASE" < "$fifo"; then
    restore_ok=false
fi
if ! wait "$decrypt_pid"; then
    restore_ok=false
fi
decrypt_pid=""
rm -f "$fifo"

if [ "$restore_ok" != true ]; then
    echo "Restore or authenticated decryption failed" >&2
    exit 1
fi

revision="$(psql --no-psqlrc --tuples-only --no-align --command='SELECT version_num FROM alembic_version')"
profile_count="$(psql --no-psqlrc --tuples-only --no-align --command='SELECT count(*) FROM user_profile')"
case "$revision" in
    0001|0002) ;;
    *)
        echo "Restored schema revision is unsupported" >&2
        exit 1
        ;;
esac
if [ "$profile_count" != "1" ]; then
    echo "Restored single-user invariant is invalid" >&2
    exit 1
fi

unset PGPASSWORD
trap - EXIT HUP INT TERM
echo "Restore completed in the isolated PlateOS database"
