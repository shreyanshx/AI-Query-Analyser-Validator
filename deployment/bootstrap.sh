#!/usr/bin/env bash
#
# AIQAV EC2 bootstrap script.
#
# Idempotently provisions a single raw Amazon EC2 t3.micro to run BOTH the
# React frontend (served as static files by Nginx) and the FastAPI backend
# (Gunicorn + Uvicorn workers under systemd). No Docker, no ECS/Fargate.
#
# Architecture recap:
#   ALB (HTTPS, ACM)  ->  EC2:80 (Nginx)  ->  127.0.0.1:8000 (FastAPI/Gunicorn)
#   Nginx serves /var/www/aiqav (React build) and proxies /api + /health.
#
# Supports Amazon Linux 2023 (dnf) and Ubuntu 22.04+ (apt). Re-running is safe.
#
# Usage (as a user with sudo, on a fresh instance):
#   sudo bash deployment/bootstrap.sh
#
# Account-specific values are read from the environment with sensible defaults;
# override them inline, e.g.:
#   sudo REPO_URL=https://github.com/ORG/AI-Query-Analyser-Validator.git \
#        REPO_BRANCH=main bash deployment/bootstrap.sh

set -euo pipefail

# --------------------------------------------------------------------------- #
# Configuration (override via environment). Placeholders -> replace for prod.  #
# --------------------------------------------------------------------------- #
APP_USER="${APP_USER:-aiqav}"
APP_GROUP="${APP_GROUP:-aiqav}"
APP_ROOT="${APP_ROOT:-/opt/aiqav}"
REPO_URL="${REPO_URL:-https://github.com/REPLACE_ME_ORG/AI-Query-Analyser-Validator.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${APP_ROOT}/AI-Query-Analyser-Validator"
WEB_ROOT="${WEB_ROOT:-/var/www/aiqav}"
ENV_DIR="${ENV_DIR:-/etc/aiqav}"
BACKEND_ENV_FILE="${ENV_DIR}/backend.env"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
NODE_MAJOR="${NODE_MAJOR:-20}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n==> %s\n' "$*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
  fi
}

detect_pkg_mgr() {
  if command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  else
    echo "unsupported"
  fi
}

# --------------------------------------------------------------------------- #
# Package installation                                                        #
# --------------------------------------------------------------------------- #
install_packages_dnf() {
  log "Installing packages via dnf (Amazon Linux 2023 / RHEL family)"
  dnf -y update
  dnf -y install git nginx gcc "python${PYTHON_VERSION}" "python${PYTHON_VERSION}-devel" || \
    dnf -y install git nginx gcc python3.11 python3.11-devel

  # Node.js 20+ from NodeSource.
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt "${NODE_MAJOR}" ]]; then
    curl -fsSL "https://rpm.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    dnf -y install nodejs
  fi
}

install_packages_apt() {
  log "Installing packages via apt (Ubuntu/Debian family)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y software-properties-common curl ca-certificates git nginx gcc
  # deadsnakes provides python3.11 on Ubuntu where it is not the default.
  if ! command -v "python${PYTHON_VERSION}" >/dev/null 2>&1; then
    add-apt-repository -y ppa:deadsnakes/ppa || true
    apt-get update -y
    apt-get install -y "python${PYTHON_VERSION}" "python${PYTHON_VERSION}-venv" "python${PYTHON_VERSION}-dev"
  fi

  # Node.js 20+ from NodeSource.
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt "${NODE_MAJOR}" ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
  fi
}

install_packages() {
  case "$(detect_pkg_mgr)" in
    dnf) install_packages_dnf ;;
    apt) install_packages_apt ;;
    *) echo "Unsupported package manager (need dnf or apt-get)." >&2; exit 1 ;;
  esac
}

# --------------------------------------------------------------------------- #
# Application user and directories                                            #
# --------------------------------------------------------------------------- #
ensure_user_and_dirs() {
  log "Ensuring application user '${APP_USER}' and directories exist"
  if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${APP_GROUP}"
  fi
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --gid "${APP_GROUP}" --home-dir "${APP_ROOT}" \
      --shell /usr/sbin/nologin "${APP_USER}" 2>/dev/null || \
    useradd --system --gid "${APP_GROUP}" --home-dir "${APP_ROOT}" \
      --shell /sbin/nologin "${APP_USER}"
  fi
  mkdir -p "${APP_ROOT}" "${WEB_ROOT}" "${ENV_DIR}"
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_ROOT}"
}

# --------------------------------------------------------------------------- #
# Source checkout                                                             #
# --------------------------------------------------------------------------- #
sync_repo() {
  log "Syncing application source into ${REPO_DIR}"
  if [[ -d "${REPO_DIR}/.git" ]]; then
    git -C "${REPO_DIR}" fetch --all --prune
    git -C "${REPO_DIR}" checkout "${REPO_BRANCH}"
    git -C "${REPO_DIR}" pull --ff-only origin "${REPO_BRANCH}"
  else
    git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${REPO_DIR}"
  fi
  chown -R "${APP_USER}:${APP_GROUP}" "${REPO_DIR}"
}

# --------------------------------------------------------------------------- #
# Frontend build                                                              #
# --------------------------------------------------------------------------- #
build_frontend() {
  log "Building React frontend and publishing to ${WEB_ROOT}"
  # Build-time frontend config. Create frontend/.env.production with your real
  # VITE_* values before running (see deployment/README.md and .env.example).
  pushd "${REPO_DIR}/frontend" >/dev/null
  npm ci
  npm run build
  popd >/dev/null

  # Publish the static build. Nginx serves this directory.
  rm -rf "${WEB_ROOT:?}/"*
  cp -r "${REPO_DIR}/frontend/dist/." "${WEB_ROOT}/"
  chown -R "${APP_USER}:${APP_GROUP}" "${WEB_ROOT}"
}

# --------------------------------------------------------------------------- #
# Backend virtualenv + dependencies                                          #
# --------------------------------------------------------------------------- #
build_backend() {
  log "Creating backend virtualenv and installing dependencies"
  pushd "${REPO_DIR}/backend" >/dev/null
  "python${PYTHON_VERSION}" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  # Install the backend package plus gunicorn for the systemd service.
  ./.venv/bin/pip install -e .
  ./.venv/bin/pip install gunicorn uvicorn
  popd >/dev/null
  chown -R "${APP_USER}:${APP_GROUP}" "${REPO_DIR}/backend/.venv"
}

# --------------------------------------------------------------------------- #
# Backend runtime environment file                                            #
# --------------------------------------------------------------------------- #
ensure_backend_env() {
  log "Ensuring backend environment file at ${BACKEND_ENV_FILE}"
  if [[ ! -f "${BACKEND_ENV_FILE}" ]]; then
    # Seed from the repo's root .env.example, keeping only backend (non-VITE_)
    # keys. REPLACE the placeholder values with real configuration, and prefer
    # supplying provider API keys via SECRETS_MANAGER_SECRET_ID.
    grep -E '^[A-Z]' "${REPO_DIR}/.env.example" | grep -v '^VITE_' > "${BACKEND_ENV_FILE}" || true
    echo "  -> Created ${BACKEND_ENV_FILE} from .env.example placeholders. EDIT IT before production use."
  else
    echo "  -> ${BACKEND_ENV_FILE} already exists; leaving as-is."
  fi
  chmod 600 "${BACKEND_ENV_FILE}"
  chown root:"${APP_GROUP}" "${BACKEND_ENV_FILE}"
}

# --------------------------------------------------------------------------- #
# Nginx + systemd wiring                                                      #
# --------------------------------------------------------------------------- #
install_nginx_conf() {
  log "Installing Nginx site configuration"
  local src="${SCRIPT_DIR}/nginx/aiqav.conf"
  if [[ -d /etc/nginx/conf.d ]]; then
    cp "${src}" /etc/nginx/conf.d/aiqav.conf
    # Disable the stock default server if present to avoid conflicts.
    [[ -f /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default
  fi
  if [[ -d /etc/nginx/sites-available ]]; then
    cp "${src}" /etc/nginx/sites-available/aiqav.conf
    ln -sf /etc/nginx/sites-available/aiqav.conf /etc/nginx/sites-enabled/aiqav.conf
    [[ -f /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default
  fi
  nginx -t
}

install_systemd_unit() {
  log "Installing systemd unit for the backend"
  cp "${SCRIPT_DIR}/systemd/aiqav-backend.service" /etc/systemd/system/aiqav-backend.service
  systemctl daemon-reload
}

enable_services() {
  log "Enabling and (re)starting services"
  systemctl enable --now aiqav-backend
  systemctl restart aiqav-backend
  systemctl enable --now nginx
  systemctl restart nginx
}

# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
main() {
  require_root
  install_packages
  ensure_user_and_dirs
  sync_repo
  build_frontend
  build_backend
  ensure_backend_env
  install_nginx_conf
  install_systemd_unit
  enable_services
  log "Bootstrap complete. FastAPI on 127.0.0.1:8000; Nginx serving ${WEB_ROOT} on :80."
  log "Point the ALB target group health check at /health."
}

main "$@"
