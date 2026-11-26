#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${PGHOST:?Set PGHOST}"
: "${PGUSER:?Set PGUSER}"
: "${PGPASSWORD:?Set PGPASSWORD (use a secret manager)}"
: "${TARGET_PGDATABASE:?Set TARGET_PGDATABASE to the explicit recovery database}"
: "${BACKUP_FILE:?Set BACKUP_FILE}"
: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=OVERWRITE_TARGET_DATABASE to proceed}"
: "${PRODUCTION_PGDATABASE:?Set PRODUCTION_PGDATABASE to protect the live database name}"
: "${PGSSLROOTCERT:?Set PGSSLROOTCERT to the trusted PostgreSQL CA certificate}"
if [[ "$RESTORE_CONFIRM" != "OVERWRITE_TARGET_DATABASE" ]]; then
  echo "Refusing restore: explicit RESTORE_CONFIRM=OVERWRITE_TARGET_DATABASE is required" >&2
  exit 64
fi
if [[ "$TARGET_PGDATABASE" == "$PRODUCTION_PGDATABASE" ]]; then
  echo "Refusing restore into the production database; use an isolated recovery target" >&2
  exit 64
fi
if [[ ! "$TARGET_PGDATABASE" =~ ^[A-Za-z0-9_-]{1,63}$ ]]; then
  echo "TARGET_PGDATABASE must be a valid isolated database identifier" >&2
  exit 64
fi
case "$PGSSLROOTCERT" in /*) ;; *) echo "PGSSLROOTCERT must be an absolute path" >&2; exit 64 ;; esac
if [[ ! -r "$PGSSLROOTCERT" ]]; then
  echo "PGSSLROOTCERT must be readable" >&2
  exit 66
fi
if [[ "${PGSSLMODE:-verify-full}" != "verify-full" ]]; then
  echo "Refusing restore unless PGSSLMODE=verify-full" >&2
  exit 64
fi
if [[ ! -f "$BACKUP_FILE" || ! -f "${BACKUP_FILE}.sha256" ]]; then
  echo "Backup file or SHA-256 sidecar is missing" >&2
  exit 66
fi
(cd "$(dirname "$BACKUP_FILE")" && sha256sum --check "$(basename "${BACKUP_FILE}.sha256")")
pg_restore --list "$BACKUP_FILE" >/dev/null
export PGSSLMODE="verify-full"
export PGSSLROOTCERT
# TARGET_PGDATABASE must be a pre-created isolated recovery target, never an
# implicit production default. The caller owns isolation and cutover approval.
pg_restore --exit-on-error --clean --if-exists --no-owner --no-acl \
  --host="$PGHOST" --username="$PGUSER" --dbname="$TARGET_PGDATABASE" "$BACKUP_FILE"
echo "RESTORE_COMPLETED target=${TARGET_PGDATABASE}; run integrity audit and application smoke tests before any cutover."
