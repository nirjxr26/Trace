#!/usr/bin/env sh
# ==============================================================================
# Trace - Automated Linux & POSIX Installer
# Sets up Python virtual environment, dependencies, settings, and exposes 'trace'
# ==============================================================================

set -eu

# Allowed URL protocol for all artifact downloads (HTTPS only, incl. redirects).
CURL_PROTO='=https'

VERBOSE=0
TRACE_REQ_VERSION=""
TRACE_LIST_VERSIONS=0
TRACE_REINSTALL=0
TRACE_UNINSTALL=0
TRACE_PURGE_DATA=0
TRACE_PHASE_TOTAL=6
TRACE_PHASE_DONE=0
TRACE_DOWNLOAD_SHOWN=0
TRACE_SHOWN=0
TRACE_BG_PID=""
TRACE_SPIN_IDX=0
TRACE_PY_WIN=0
case "$(uname -s 2>/dev/null || printf '')" in
  MINGW*|MSYS*|CYGWIN*) TRACE_PY_WIN=1 ;;
esac

trap '[ -n "$TRACE_BG_PID" ] && kill "$TRACE_BG_PID" 2>/dev/null; true' EXIT HUP INT TERM
TRACE_CURRENT_LABEL=""
TRACE_HOME="${HOME}/.trace"
TRACE_INSTALL_LOG="${TRACE_HOME}/install.log"
TRACE_DISPLAY_VERSION=""

trace_usage() {
  printf "%s\n" "Usage: install.sh [--version <tag>] [--list-versions] [--reinstall] [--uninstall [--purge-data]] [--verbose] [--help]"
  printf "%s\n" ""
  printf "%s\n" "  (none)              Quiet install of main (or TRACE_REF when set)"
  printf "%s\n" "  --version <tag>     Install that release instead"
  printf "%s\n" "  --list-versions     List releases; TTY offers pick-and-install"
  printf "%s\n" "  --reinstall         Wipe app code first, then install"
  printf "%s\n" "  --uninstall         Remove launcher + app + config; keeps storage and database"
  printf "%s\n" "  --uninstall --purge-data  Also remove storage; confirms first"
  printf "%s\n" "  --verbose           Full step-by-step output"
  printf "%s\n" "  --help              Usage; exit 0"
}

trace_is_tty() {
  [ -t 1 ]
}

trace_log_init() {
  mkdir -p "$TRACE_HOME" 2>/dev/null || true
  touch "$TRACE_INSTALL_LOG" 2>/dev/null || true
}

trace_say() {
  if [ "$VERBOSE" = "1" ]; then
    printf "%s\n" "$*"
  fi
  printf "%s\n" "$*" >>"$TRACE_INSTALL_LOG" 2>/dev/null || true
}

trace_winpath() {
  TRACE_WP_IN="$1"
  if [ "$TRACE_PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$TRACE_WP_IN" 2>/dev/null || printf '%s' "$TRACE_WP_IN"
  else
    printf '%s' "$TRACE_WP_IN"
  fi
}

trace_resolve_venv() {
  if [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
  elif [ -f "$VENV_DIR/bin/python" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
  else
    return 1
  fi
  TRACE_BIN="$VENV_DIR/bin/trace"
  if [ -f "$VENV_DIR/Scripts/trace.exe" ]; then
    TRACE_BIN="$VENV_DIR/Scripts/trace.exe"
  fi
  return 0
}

trace_bar_for() {
  TRACE_PCT_B="$1"
  TRACE_FILLED=$((TRACE_PCT_B * 20 / 100))
  TRACE_EMPTY=$((20 - TRACE_FILLED))
  TRACE_BAR=""
  TRACE_I=0
  while [ "$TRACE_I" -lt "$TRACE_FILLED" ]; do
    TRACE_BAR="${TRACE_BAR}█"
    TRACE_I=$((TRACE_I + 1))
  done
  TRACE_I=0
  while [ "$TRACE_I" -lt "$TRACE_EMPTY" ]; do
    TRACE_BAR="${TRACE_BAR}░"
    TRACE_I=$((TRACE_I + 1))
  done
}

trace_draw() {
  trace_bar_for "$1"
  TRACE_VER="${TRACE_DISPLAY_VERSION:-install}"
  if [ "$VERBOSE" = "1" ]; then
    return 0
  fi
  if trace_is_tty; then
    if [ "$TRACE_DOWNLOAD_SHOWN" = "0" ]; then
      TRACE_DOWNLOAD_SHOWN=1
      printf '\033[1;32m%s\033[0m\n' "Downloading Trace $TRACE_VER..."
      printf '\n'
    fi
    printf '\r\033[1;32m[%s] %s%%   \033[0m' "$TRACE_BAR" "$1"
  else
    if [ "$1" = "100" ]; then
      if [ "$TRACE_DOWNLOAD_SHOWN" = "1" ]; then
        return 0
      fi
      TRACE_DOWNLOAD_SHOWN=1
      printf '%s\n' "Downloading Trace $TRACE_VER..."
      printf '\n'
      printf '[%s] %s%%\n' "$TRACE_BAR" "$1"
      printf '\n'
    fi
  fi
}

trace_step() {
  TRACE_SHOWN=$((TRACE_SHOWN + 1))
  trace_draw "$TRACE_SHOWN"
}

trace_to() {
  TRACE_TARGET="$1"
  if [ "$VERBOSE" = "1" ]; then
    TRACE_SHOWN="$TRACE_TARGET"
    return 0
  fi
  while [ "$TRACE_SHOWN" -lt "$TRACE_TARGET" ]; do
    trace_step
    sleep 0.05 2>/dev/null || true
  done
}

trace_spin() {
  if [ "$VERBOSE" = "1" ]; then
    return 0
  fi
  if ! trace_is_tty; then
    return 0
  fi
  if [ "$TRACE_SHOWN" -lt 0 ]; then
    TRACE_SHOWN=0
  fi
  TRACE_SPIN_IDX=$((TRACE_SPIN_IDX + 1))
  case $((TRACE_SPIN_IDX % 4)) in
    0) TRACE_FRM="|" ;;
    1) TRACE_FRM="/" ;;
    2) TRACE_FRM="-" ;;
    *) TRACE_FRM="\\" ;;
  esac
  trace_bar_for "$TRACE_SHOWN"
  printf '\r\033[1;32m[%s] %s%% %s   \033[0m' "$TRACE_BAR" "$TRACE_SHOWN" "$TRACE_FRM"
}

trace_phase() {
  TRACE_PHASE_DONE=$((TRACE_PHASE_DONE + 1))
  TRACE_CURRENT_LABEL="$1"
  trace_to $((TRACE_PHASE_DONE * 100 / TRACE_PHASE_TOTAL))
}

trace_collect_tmp() {
  cat "$TRACE_TMP" >>"$TRACE_INSTALL_LOG" 2>/dev/null || true
  rm -f "$TRACE_TMP"
}

trace_run() {
  TRACE_TMP="$(mktemp)"
  if "$@" >"$TRACE_TMP" 2>&1; then
    TRACE_STATUS=0
  else
    TRACE_STATUS=$?
  fi
  if [ "$VERBOSE" = "1" ]; then
    cat "$TRACE_TMP"
  fi
  trace_collect_tmp
  return $TRACE_STATUS
}

trace_run_live() {
  TRACE_TARGET="$1"
  shift
  if [ "$VERBOSE" = "1" ] || ! trace_is_tty; then
    if trace_run "$@"; then
      TRACE_STATUS=0
    else
      TRACE_STATUS=$?
    fi
    TRACE_SHOWN="$TRACE_TARGET"
    return $TRACE_STATUS
  fi
  TRACE_TMP="$(mktemp)"
  "$@" >"$TRACE_TMP" 2>&1 &
  TRACE_BG_PID=$!
  while kill -0 "$TRACE_BG_PID" 2>/dev/null; do
    if [ "$TRACE_SHOWN" -lt "$TRACE_TARGET" ]; then
      trace_step
    else
      trace_spin
    fi
    sleep 1
  done
  if wait "$TRACE_BG_PID"; then
    TRACE_STATUS=0
  else
    TRACE_STATUS=$?
  fi
  TRACE_BG_PID=""
  trace_collect_tmp
  trace_to "$TRACE_TARGET"
  return $TRACE_STATUS
}

trace_fail() {
  TRACE_STEP="$1"
  if trace_is_tty && [ "$VERBOSE" = "0" ]; then
    printf '\n'
  fi
  printf "Install failed at '%s' - see %s\n" "$TRACE_STEP" "$TRACE_INSTALL_LOG" >&2
  if [ -f "$TRACE_INSTALL_LOG" ]; then
    tail -n 12 "$TRACE_INSTALL_LOG" >&2 2>/dev/null || true
  fi
  exit 1
}

trace_success() {
  TRACE_VER="$1"
  if trace_is_tty && [ "$VERBOSE" = "0" ]; then
    printf '\n'
  fi
  if trace_is_tty; then
    printf '\033[1;32m%s\033[0m\n' "✓ Installation complete"
    printf '\033[1;32m%s\033[0m\n' "Trace $TRACE_VER installed successfully."
  else
    printf '%s\n' "Installation complete"
    printf '%s\n' "Trace $TRACE_VER installed successfully."
  fi
}

trace_check_version() {
  TRACE_TAG="$1"
  if command -v git >/dev/null 2>&1; then
    if git ls-remote --tags https://github.com/nirjxr26/Trace.git "$TRACE_TAG" 2>>"$TRACE_INSTALL_LOG" | grep -q "$TRACE_TAG"; then
      return 0
    fi
    printf "Unknown tag '%s'. Run with --list-versions to see releases.\n" "$TRACE_TAG" >&2
    exit 1
  fi
  if command -v curl >/dev/null 2>&1; then
    if curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL "https://api.github.com/repos/nirjxr26/Trace/releases/tags/$TRACE_TAG" >>"$TRACE_INSTALL_LOG" 2>&1; then
      return 0
    fi
    printf "Unknown tag '%s'. Run with --list-versions to see releases.\n" "$TRACE_TAG" >&2
    exit 1
  fi
}

trace_list_versions() {
  TRACE_API="https://api.github.com/repos/nirjxr26/Trace/releases?per_page=20"
  TRACE_TMP="$(mktemp)"
  if ! curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -o "$TRACE_TMP" "$TRACE_API" 2>>"$TRACE_INSTALL_LOG"; then
    rm -f "$TRACE_TMP"
    printf "Could not list releases (offline?). Try --version vX.Y.Z explicitly.\n"
    exit 1
  fi
  TRACE_TAGS="$(grep '"tag_name":' "$TRACE_TMP" | cut -d'"' -f4)"
  rm -f "$TRACE_TMP"
  if [ -z "$TRACE_TAGS" ]; then
    printf "No releases found. Try --version vX.Y.Z explicitly.\n"
    exit 0
  fi
  if [ -t 1 ] && [ -t 0 ]; then
    printf "Available releases:\n"
    printf "%s\n" "$TRACE_TAGS" | cat -n
    printf "Enter number to install (empty to exit): "
    read TRACE_PICK
    if [ -z "$TRACE_PICK" ]; then
      exit 0
    fi
    TRACE_SEL="$(printf "%s\n" "$TRACE_TAGS" | sed -n "${TRACE_PICK}p")"
    if [ -z "$TRACE_SEL" ]; then
      printf "Invalid selection.\n" >&2
      exit 1
    fi
    TRACE_REF="$TRACE_SEL" sh "$0" ${TRACE_REINSTALL:+--reinstall} ${VERBOSE:+--verbose}
    exit $?
  else
    printf "%s\n" "$TRACE_TAGS"
    exit 0
  fi
}

trace_do_uninstall() {
  TRACE_APP_DIR="${HOME}/.trace/app"
  TRACE_SHIM="${HOME}/.local/bin/trace"
  TRACE_ENV_FILE=""
  if [ -n "${REPO_ROOT:-}" ] && [ -f "${REPO_ROOT}/.env" ]; then
    TRACE_ENV_FILE="${REPO_ROOT}/.env"
  fi
  if [ "$TRACE_PURGE_DATA" = "1" ]; then
    if [ -t 0 ]; then
      printf "Remove storage and config? Database server is kept. Confirm y/N: "
      read TRACE_CONFIRM
      if [ "$TRACE_CONFIRM" != "y" ] && [ "$TRACE_CONFIRM" != "Y" ]; then
        printf "Cancelled.\n"
        exit 0
      fi
    fi
  fi
  rm -f "$TRACE_SHIM" 2>/dev/null || true
  if [ -d "$TRACE_APP_DIR" ]; then
    rm -rf "$TRACE_APP_DIR" 2>>"$TRACE_INSTALL_LOG" || trace_fail "uninstall"
  fi
  if [ -n "$TRACE_ENV_FILE" ]; then
    rm -f "$TRACE_ENV_FILE" 2>/dev/null || true
  fi
  if [ -f "${HOME}/.trace/app/.env" ]; then
    rm -f "${HOME}/.trace/app/.env" 2>/dev/null || true
  fi
  if [ "$TRACE_PURGE_DATA" = "1" ]; then
    rm -rf "${HOME}/.trace/trust" 2>/dev/null || true
    rm -rf "${HOME}/.trace/storage" 2>/dev/null || true
    printf "Removed launcher, app, config, trust, storage.\n"
    printf "Kept: PostgreSQL server. To drop data run: DROP DATABASE trace;\n"
  else
    printf "Removed launcher, app, config.\n"
    printf "Kept: storage (~/.trace/storage), trust keys, PostgreSQL database.\n"
  fi
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      TRACE_REQ_VERSION="${2:-}"
      shift 2
      ;;
    --version=*)
      TRACE_REQ_VERSION="${1#--version=}"
      shift
      ;;
    --list-versions)
      TRACE_LIST_VERSIONS=1
      shift
      ;;
    --reinstall)
      TRACE_REINSTALL=1
      shift
      ;;
    --uninstall)
      TRACE_UNINSTALL=1
      shift
      ;;
    --purge-data)
      TRACE_PURGE_DATA=1
      shift
      ;;
    --verbose)
      VERBOSE=1
      shift
      ;;
    --help|-h)
      trace_usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      printf "Unknown flag '%s'. Run with --help.\n" "$1" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

trace_log_init
printf "install started %s flags verbose=%s reinstall=%s uninstall=%s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)" "$VERBOSE" "$TRACE_REINSTALL" "$TRACE_UNINSTALL" >>"$TRACE_INSTALL_LOG" 2>/dev/null || true

if [ -n "$TRACE_REQ_VERSION" ]; then
  TRACE_REF="$TRACE_REQ_VERSION"
  export TRACE_REF
  trace_check_version "$TRACE_REQ_VERSION"
elif [ -n "${TRACE_REF:-}" ]; then
  export TRACE_REF
fi

if [ "$TRACE_LIST_VERSIONS" = "1" ]; then
  trace_list_versions
fi

# Determine repository root (support local execution and remote 'curl ... | sh' execution)
SCRIPT_DIR=""
if [ -n "${0:-}" ] && [ "$0" != "sh" ] && [ "$0" != "-sh" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    REPO_ROOT="$SCRIPT_DIR"
elif [ -f "$(pwd)/pyproject.toml" ]; then
    REPO_ROOT="$(pwd)"
else
    TRACE_HOME="${HOME}/.trace"
    REPO_ROOT="${TRACE_HOME}/app"
    if [ "$VERBOSE" = "1" ]; then
      printf "Remote installation detected. Setting up Trace in '%s'...\n" "$REPO_ROOT"
    fi
    printf "remote install root %s ref %s\n" "$REPO_ROOT" "${TRACE_REF:-main}" >>"$TRACE_INSTALL_LOG" 2>/dev/null || true

    if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
        mkdir -p "$TRACE_HOME"
        TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
        TRACE_REF="${TRACE_REF:-main}"
        case "$TRACE_REF" in
            v*) REF_KIND="tags" ;;
            *) REF_KIND="heads" ;;
        esac
        if [ -n "$TOKEN" ]; then
            AUTH_HEADER="Authorization: Bearer ${TOKEN}"
        else
            AUTH_HEADER=""
        fi

        if command -v git >/dev/null 2>&1; then
            trace_say "Cloning repository via git (ref: $TRACE_REF)..."
            if [ -n "$TOKEN" ]; then
                ASKPASS_FILE="$(mktemp)"
                { echo '#!/usr/bin/env sh'; echo 'exec printf "%s" "$TRACE_GIT_TOKEN"'; } > "$ASKPASS_FILE"
                chmod 700 "$ASKPASS_FILE"
                TRACE_GIT_TOKEN="$TOKEN" GIT_ASKPASS="$ASKPASS_FILE" GIT_TERMINAL_PROMPT=0 \
                    git clone --depth 1 --branch "$TRACE_REF" https://github.com/nirjxr26/Trace.git "$REPO_ROOT" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                rm -f "$ASKPASS_FILE"
                unset TRACE_GIT_TOKEN
            else
                git clone --depth 1 --branch "$TRACE_REF" https://github.com/nirjxr26/Trace.git "$REPO_ROOT" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
            fi
        else
            trace_say "Downloading repository archive..."
            ARCHIVE_URL="https://github.com/nirjxr26/Trace/archive/refs/${REF_KIND}/${TRACE_REF}.tar.gz"
            mkdir -p "$REPO_ROOT"
            if [ -n "${TRACE_RELEASE_SHA256:-}" ]; then
                if ! command -v sha256sum >/dev/null 2>&1; then
                    printf "  [!] sha256sum missing: cannot verify pinned release. Aborting.\n" >&2
                    exit 1
                fi
                ARCHIVE_FILE="$(mktemp)"
                if [ -n "$AUTH_HEADER" ]; then
                    curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -H "$AUTH_HEADER" -o "$ARCHIVE_FILE" "$ARCHIVE_URL" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                else
                    curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -o "$ARCHIVE_FILE" "$ARCHIVE_URL" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                fi
                ACTUAL_SHA="$(sha256sum "$ARCHIVE_FILE" | cut -d' ' -f1)"
                if [ "$ACTUAL_SHA" != "$TRACE_RELEASE_SHA256" ]; then
                    printf "  [!] Release digest mismatch: refusing to install.\n" >&2
                    rm -f "$ARCHIVE_FILE"
                    exit 1
                fi
                if [ -n "${TRACE_COSIGN_BUNDLE_URL:-}" ] && command -v cosign >/dev/null 2>&1; then
                    curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -o "${ARCHIVE_FILE}.sigstore.json" "$TRACE_COSIGN_BUNDLE_URL" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                    cosign verify-blob --bundle "${ARCHIVE_FILE}.sigstore.json" \
                        --certificate-identity "${TRACE_COSIGN_IDENTITY:?set TRACE_COSIGN_IDENTITY}" \
                        --certificate-oidc-issuer "${TRACE_COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}" \
                        "$ARCHIVE_FILE" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                    rm -f "${ARCHIVE_FILE}.sigstore.json"
                fi
                tar -xz --strip-components=1 -C "$REPO_ROOT" -f "$ARCHIVE_FILE" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                rm -f "$ARCHIVE_FILE"
            else
                trace_say "  [!] No TRACE_RELEASE_SHA256 pinned: installing unverified $TRACE_REF."
                if [ -n "$AUTH_HEADER" ]; then
                    curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -H "$AUTH_HEADER" "$ARCHIVE_URL" 2>>"$TRACE_INSTALL_LOG" | tar -xz --strip-components=1 -C "$REPO_ROOT" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                else
                    curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL "$ARCHIVE_URL" 2>>"$TRACE_INSTALL_LOG" | tar -xz --strip-components=1 -C "$REPO_ROOT" >>"$TRACE_INSTALL_LOG" 2>&1 || trace_fail "source"
                fi
            fi
        fi
    fi
fi

if [ "$TRACE_UNINSTALL" = "1" ]; then
  trace_do_uninstall
fi

if [ "$TRACE_REINSTALL" = "1" ]; then
  case "$REPO_ROOT" in
    "${HOME}/.trace/app")
      rm -rf "$REPO_ROOT" 2>>"$TRACE_INSTALL_LOG" || trace_fail "source"
      ;;
    *)
      if [ -d "$REPO_ROOT/.venv" ]; then
        rm -rf "$REPO_ROOT/.venv" 2>>"$TRACE_INSTALL_LOG" || trace_fail "venv"
      fi
      if [ -d "${HOME}/.trace/app" ]; then
        rm -rf "${HOME}/.trace/app" 2>>"$TRACE_INSTALL_LOG" || trace_fail "source"
      fi
      ;;
  esac
  if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    printf "Reinstall requested but source is gone. Re-run without --reinstall or pass --version.\n" >&2
    exit 1
  fi
fi

cd "$REPO_ROOT"
SCRIPT_DIR="$REPO_ROOT"

if [ -f "$REPO_ROOT/pyproject.toml" ]; then
  TRACE_DISPLAY_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO_ROOT/pyproject.toml" | head -n 1)"
fi
if [ -z "$TRACE_DISPLAY_VERSION" ]; then
  TRACE_DISPLAY_VERSION="${TRACE_REF:-main}"
fi

if [ "$VERBOSE" = "1" ]; then
  printf "\n"
  printf "  ================================================================\n"
  printf "         TRACE - Forensic Data Imaging & Retrieval Tool           \n"
  printf "                           Linux Installer                        \n"
  printf "  ================================================================\n"
  printf "\n"
fi

trace_phase "python"
if [ "$VERBOSE" = "1" ]; then
  printf "[1/6] Searching for Python 3.12+...\n"
fi
FOUND_PYTHON=""

for cmd in python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VERSION="$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")"
        if [ -n "$PY_VERSION" ]; then
            MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
            MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
            if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 12 ]; then
                FOUND_PYTHON="$cmd"
                trace_say "  [OK] Found Python $PY_VERSION using '$cmd'"
                break
            fi
        fi
    fi
done

if [ -z "$FOUND_PYTHON" ]; then
    printf "\n"
    printf "  [!] Error: Python 3.12 or higher was not found on your system.\n"
    printf "  Please install Python 3.12+ using your distribution's package manager:\n"
    printf "      Ubuntu/Debian:  sudo apt update && sudo apt install python3.12 python3.12-venv\n"
    printf "      Fedora/RHEL:    sudo dnf install python3.12\n"
    printf "      Arch Linux:     sudo pacman -S python\n"
    trace_fail "python"
fi

trace_phase "source"
trace_say "Source ready at $REPO_ROOT"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

trace_phase "venv"
if [ "$VERBOSE" = "1" ]; then
  printf "[3/6] Configuring virtual environment...\n"
fi
if ! trace_resolve_venv; then
    trace_say "  Creating virtual environment at '$VENV_DIR'..."
    VENV_CREATE_DIR="$(trace_winpath "$VENV_DIR")"
    trace_run_live 50 "$FOUND_PYTHON" -m venv "$VENV_CREATE_DIR" || trace_fail "venv"
    trace_resolve_venv || trace_fail "venv"
else
    trace_say "  [OK] Existing virtual environment detected."
fi

trace_phase "dependencies"
if [ "$VERBOSE" = "1" ]; then
  printf "[4/6] Installing locked dependencies...\n"
  printf "  Using pip with cryptographic hash verification...\n"
fi
trace_run_live 66 "$VENV_PYTHON" -m pip install --quiet "pip==26.2.1" || trace_fail "dependencies"
trace_run_live 66 "$VENV_PYTHON" -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt || trace_fail "dependencies"
trace_run_live 66 "$VENV_PYTHON" -m pip install --quiet --no-deps -e . || trace_fail "dependencies"
trace_say "  [OK] Dependencies installed successfully."

trace_phase "config"
if [ "$VERBOSE" = "1" ]; then
  printf "[5/6] Verifying environment & storage directories...\n"
fi
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        chmod 600 "$SCRIPT_DIR/.env"
        if ! grep -q "^TRACE_UPDATE_MANIFEST=" "$SCRIPT_DIR/.env"; then
            printf '%s\n' "TRACE_UPDATE_MANIFEST=https://github.com/nirjxr26/Trace/releases/latest/download/stable.json" >> "$SCRIPT_DIR/.env"
        fi
        trace_say "  [OK] Created .env from template (.env.example)."
        trace_say "  [!] Set a strong TRACE_DATABASE_URL password and TRACE_SECRET_KEY before production use."
    fi
else
    trace_say "  [OK] Existing .env file preserved."
fi

TRUST_DIR="${HOME}/.trace/trust/releases"
if mkdir -p "$TRUST_DIR" 2>/dev/null; then
    BUNDLE_FILE="$(mktemp)"
    if trace_run_live 83 curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -o "$BUNDLE_FILE" "https://github.com/nirjxr26/Trace/releases/latest/download/trusted-keys.bundle"; then
        while IFS=' ' read -r _fp _hex _rest; do
            case "$_fp" in
                ????????????????) ;;
                *) continue ;;
            esac
            case "$_fp" in
                *[!0-9a-f]*|'') continue ;;
                *) ;;
            esac
            case "$_hex" in
                ????????????????????????????????????????????????????????????????) ;;
                *) continue ;;
            esac
            case "$_hex" in
                *[!0-9a-f]*|'') continue ;;
                *) ;;
            esac
            printf '%s' "$_hex" > "$TRUST_DIR/${_fp}.pub"
        done < "$BUNDLE_FILE"
        trace_say "  [OK] Release trust keys provisioned."
    else
        trace_say "  [!] Could not fetch release trust keys (offline or no release yet). Verification stays fail-closed until provisioned."
    fi
    rm -f "$BUNDLE_FILE"
fi

DEFAULT_STORAGE="${HOME}/.trace/storage"
if [ ! -d "$DEFAULT_STORAGE" ]; then
    mkdir -p "$DEFAULT_STORAGE"
    trace_say "  [OK] Created forensic storage directory at '$DEFAULT_STORAGE'."
else
    trace_say "  [OK] Forensic storage directory exists."
fi

if [ "${SKIP_DB_MIGRATION:-0}" != "1" ]; then
    trace_resolve_venv || trace_fail "config"
    if trace_run_live 83 "$TRACE_BIN" doctor; then
        trace_say "  [OK] Database verified and up to date."
    else
        trace_say "  [!] Database unreachable. Trace will self-initialize on first use once it is reachable."
        trace_say "      Start PostgreSQL or set TRACE_DATABASE_URL in .env, then run 'trace doctor' to verify."
    fi
else
    trace_say "  Skipping database verification as requested."
fi

trace_phase "launcher"
if [ "$VERBOSE" = "1" ]; then
  printf "[6/6] Exposing 'trace' command to ~/.local/bin...\n"
fi
USER_BIN="${HOME}/.local/bin"
mkdir -p "$USER_BIN"

trace_resolve_venv || trace_fail "launcher"
LAUNCHER_SCRIPT="$USER_BIN/trace"
cat <<EOF > "$LAUNCHER_SCRIPT"
#!/usr/bin/env sh
exec "$TRACE_BIN" "\$@"
EOF
chmod +x "$LAUNCHER_SCRIPT"
trace_say "  [OK] Installed launcher script to '$LAUNCHER_SCRIPT'."

TRACE_SHORT_VER="$TRACE_DISPLAY_VERSION"
trace_success "v$TRACE_SHORT_VER"
