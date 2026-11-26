#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${PGHOST:?Set PGHOST}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGUSER:?Set PGUSER}"
: "${PGPASSWORD:?Set PGPASSWORD (use a secret manager)}"
: "${BACKUP_DIR:?Set BACKUP_DIR to a platform-KMS-encrypted backup volume}"
: "${BACKUP_ENCRYPTION_KEY_REFERENCE:?Set the platform KMS backup key reference}"
: "${PGSSLROOTCERT:?Set PGSSLROOTCERT to the trusted PostgreSQL CA certificate}"
if [[ "${PGSSLMODE:-verify-full}" != "verify-full" ]]; then
  echo "Refusing backup unless PGSSLMODE=verify-full" >&2
  exit 64
fi
case "$PGSSLROOTCERT" in /*) ;; *) echo "PGSSLROOTCERT must be an absolute path" >&2; exit 64 ;; esac
if [[ ! -r "$PGSSLROOTCERT" ]]; then
  echo "PGSSLROOTCERT must be readable" >&2
  exit 66
fi
export PGSSLMODE="verify-full"
export PGSSLROOTCERT

mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
created_at="$(date -u +%Y%m%dT%H%M%SZ)"
tmp_file="$(mktemp "$BACKUP_DIR/.data_ai_${created_at}.XXXXXX")"
random_suffix="$(basename "$tmp_file" | awk -F. '{print $NF}')"
backup_file="$BACKUP_DIR/data_ai_${created_at}_${random_suffix}.dump"
trap 'rm -f "$tmp_file"' EXIT

pg_dump --format=custom --no-owner --no-acl --file="$tmp_file"
# Validate archive catalog before publishing it as a completed backup.
pg_restore --list "$tmp_file" >/dev/null
mv "$tmp_file" "$backup_file"
sha256sum "$backup_file" > "${backup_file}.sha256"
chmod 0600 "$backup_file" "${backup_file}.sha256"

printf '{"status":"BACKUP_CREATED","created_at":"%s","file":"%s","sha256_file":"%s","encryption_key_reference":"%s","catalog_verified":true}\n' \
  "$created_at" "$(basename "$backup_file")" "$(basename "${backup_file}.sha256")" "$BACKUP_ENCRYPTION_KEY_REFERENCE"
