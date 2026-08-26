#!/bin/sh
set -eu

umask 077

password_file=/run/secrets/plateos_database_password
recipient_file=/run/secrets/plateos_backup_recipient
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
filename="plateos-${timestamp}.dump.age"
final_path="/backups/${filename}"
checksum_path="${final_path}.sha256"
temporary_path="/backups/.${filename}.$$.tmp"
checksum_temporary_path="/backups/.${filename}.$$.sha256.tmp"
fifo="/tmp/plateos-backup-$$.fifo"
lock_dir=/backups/.plateos-backup.lock
encrypt_pid=""
lock_acquired=false
publication_started=false
backup_published=false

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$encrypt_pid" ] && kill -0 "$encrypt_pid" 2>/dev/null; then
        kill "$encrypt_pid" 2>/dev/null || true
        wait "$encrypt_pid" 2>/dev/null || true
    fi
    rm -f "$fifo" "$temporary_path" "$checksum_temporary_path"
    if [ "$publication_started" = true ] && [ "$backup_published" != true ]; then
        rm -f "$final_path" "$checksum_path"
    fi
    if [ "$lock_acquired" = true ]; then
        rmdir "$lock_dir" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for variable in PGHOST PGPORT PGUSER PGDATABASE; do
    eval "value=\${$variable:-}"
    if [ -z "$value" ]; then
        echo "$variable is required" >&2
        exit 1
    fi
done

if [ ! -r "$password_file" ] || [ ! -r "$recipient_file" ]; then
    echo "Database password and age recipient files must be readable" >&2
    exit 1
fi
if [ ! -d /backups ] || [ ! -w /backups ]; then
    echo "Backup destination must exist and be writable" >&2
    exit 1
fi
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "Another backup is running or a stale backup lock exists" >&2
    exit 1
fi
lock_acquired=true
if [ -e "$final_path" ] || [ -e "$checksum_path" ]; then
    echo "Refusing to overwrite an existing backup" >&2
    exit 1
fi

recipient="$(cat "$recipient_file")"
if [ -z "$recipient" ]; then
    echo "Age recipient is empty" >&2
    exit 1
fi
export PGPASSWORD="$(cat "$password_file")"

if ! revision="$(psql --no-psqlrc --tuples-only --no-align \
    --set=ON_ERROR_STOP=1 \
    --command='SELECT version_num FROM alembic_version' 2>/dev/null)"; then
    echo "Database is not an initialized PlateOS database" >&2
    exit 1
fi
case "$revision" in
    0001|0002|0003) ;;
    *)
        echo "Database schema revision is unsupported for backup" >&2
        exit 1
        ;;
esac
if ! profile_count="$(psql --no-psqlrc --tuples-only --no-align \
    --set=ON_ERROR_STOP=1 \
    --command='SELECT count(*) FROM user_profile' 2>/dev/null)"; then
    echo "Database is missing the PlateOS profile table" >&2
    exit 1
fi
if [ "$profile_count" -lt 1 ]; then
    echo "PlateOS account invariant invalid (no users); backup refused" >&2
    exit 1
fi

mkfifo "$fifo"
age --recipient "$recipient" --output "$temporary_path" "$fifo" &
encrypt_pid=$!

if ! pg_dump \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges > "$fifo"; then
    wait "$encrypt_pid" 2>/dev/null || true
    encrypt_pid=""
    echo "pg_dump failed; partial encrypted output removed" >&2
    exit 1
fi
if ! wait "$encrypt_pid"; then
    encrypt_pid=""
    echo "Backup encryption failed; partial output removed" >&2
    exit 1
fi
encrypt_pid=""
unset PGPASSWORD

if [ ! -s "$temporary_path" ]; then
    echo "Encrypted backup is empty" >&2
    exit 1
fi
checksum_output="$(sha256sum "$temporary_path")"
checksum="${checksum_output%% *}"
if [ -z "$checksum" ]; then
    echo "Encrypted backup checksum failed" >&2
    exit 1
fi
printf '%s  %s\n' "$checksum" "$filename" > "$checksum_temporary_path"

# Publish the archive last so consumers never see it without its checksum.
publication_started=true
mv "$checksum_temporary_path" "$checksum_path"
mv "$temporary_path" "$final_path"
backup_published=true

rm -f "$fifo"
rmdir "$lock_dir"
lock_acquired=false
trap - EXIT HUP INT TERM
echo "Created encrypted database backup: ${filename}"
