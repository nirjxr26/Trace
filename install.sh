#!/usr/bin/env sh
# ==============================================================================
# Trace — Automated Linux & POSIX Installer
# Sets up Python virtual environment, dependencies, settings, and exposes 'trace'
# ==============================================================================

set -eu

# Determine repository root (support local execution and remote 'curl ... | sh' execution)
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
elif [ -n "${0:-}" ] && [ "$0" != "sh" ] && [ "$0" != "-sh" ] && [ "$0" != "bash" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    REPO_ROOT="$SCRIPT_DIR"
elif [ -f "$(pwd)/pyproject.toml" ]; then
    REPO_ROOT="$(pwd)"
else
    # Remote execution mode: download repository into ~/.trace/app
    TRACE_HOME="${HOME}/.trace"
    REPO_ROOT="${TRACE_HOME}/app"
    printf "\033[1;36mRemote installation detected. Setting up Trace in '%s'...\033[0m\n" "$REPO_ROOT"

    if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
        mkdir -p "$TRACE_HOME"
        TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
        # Pinned ref: set TRACE_REF to a signed release tag in production (default tracks main).
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
            printf "Cloning repository via git (ref: %s)...\n" "$TRACE_REF"
            if [ -n "$TOKEN" ]; then
                # Never put secrets in the remote URL: GIT_ASKPASS answers the
                # credential prompt from the environment, so nothing is persisted
                # in .git/config and the token never appears in process listings.
                ASKPASS_FILE="$(mktemp)"
                { echo '#!/usr/bin/env sh'; echo 'exec printf "%s" "$TRACE_GIT_TOKEN"'; } > "$ASKPASS_FILE"
                chmod 700 "$ASKPASS_FILE"
                TRACE_GIT_TOKEN="$TOKEN" GIT_ASKPASS="$ASKPASS_FILE" GIT_TERMINAL_PROMPT=0 \
                    git clone --depth 1 --branch "$TRACE_REF" https://github.com/nirjxr26/Trace.git "$REPO_ROOT"
                rm -f "$ASKPASS_FILE"
                unset TRACE_GIT_TOKEN
            else
                git clone --depth 1 --branch "$TRACE_REF" https://github.com/nirjxr26/Trace.git "$REPO_ROOT"
            fi
        else
            printf "Downloading repository archive...\n"
            ARCHIVE_URL="https://github.com/nirjxr26/Trace/archive/refs/${REF_KIND}/${TRACE_REF}.tar.gz"
            mkdir -p "$REPO_ROOT"
            if [ -n "${TRACE_RELEASE_SHA256:-}" ]; then
                # Pinned release: verify digest before extraction, fail closed on mismatch.
                if ! command -v sha256sum >/dev/null 2>&1; then
                    printf "  [!] sha256sum missing: cannot verify pinned release. Aborting.\n" >&2
                    exit 1
                fi
                ARCHIVE_FILE="$(mktemp)"
                if [ -n "$AUTH_HEADER" ]; then
                    curl --proto '=https' --proto-redir '=https' -fsSL -H "$AUTH_HEADER" -o "$ARCHIVE_FILE" "$ARCHIVE_URL"
                else
                    curl --proto '=https' --proto-redir '=https' -fsSL -o "$ARCHIVE_FILE" "$ARCHIVE_URL"
                fi
                ACTUAL_SHA="$(sha256sum "$ARCHIVE_FILE" | cut -d' ' -f1)"
                if [ "$ACTUAL_SHA" != "$TRACE_RELEASE_SHA256" ]; then
                    printf "  [!] Release digest mismatch: refusing to install.\n" >&2
                    rm -f "$ARCHIVE_FILE"
                    exit 1
                fi
                if [ -n "${TRACE_COSIGN_BUNDLE_URL:-}" ] && command -v cosign >/dev/null 2>&1; then
                    curl --proto '=https' --proto-redir '=https' -fsSL -o "${ARCHIVE_FILE}.sigstore.json" "$TRACE_COSIGN_BUNDLE_URL"
                    cosign verify-blob --bundle "${ARCHIVE_FILE}.sigstore.json" \
                        --certificate-identity "${TRACE_COSIGN_IDENTITY:?set TRACE_COSIGN_IDENTITY}" \
                        --certificate-oidc-issuer "${TRACE_COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}" \
                        "$ARCHIVE_FILE"
                    rm -f "${ARCHIVE_FILE}.sigstore.json"
                fi
                tar -xz --strip-components=1 -C "$REPO_ROOT" -f "$ARCHIVE_FILE"
                rm -f "$ARCHIVE_FILE"
            else
                printf "  [!] No TRACE_RELEASE_SHA256 pinned: installing unverified %s.\n" "$TRACE_REF"
                if [ -n "$AUTH_HEADER" ]; then
                    curl --proto '=https' --proto-redir '=https' -fsSL -H "$AUTH_HEADER" "$ARCHIVE_URL" | tar -xz --strip-components=1 -C "$REPO_ROOT"
                else
                    curl --proto '=https' --proto-redir '=https' -fsSL "$ARCHIVE_URL" | tar -xz --strip-components=1 -C "$REPO_ROOT"
                fi
            fi
        fi
    fi
fi

cd "$REPO_ROOT"
SCRIPT_DIR="$REPO_ROOT"

printf "\n"
printf "\033[1;36m  ================================================================\033[0m\n"
printf "\033[1;36m         TRACE — Forensic Data Imaging & Retrieval Tool           \033[0m\n"
printf "\033[1;36m                           Linux Installer                        \033[0m\n"
printf "\033[1;36m  ================================================================\033[0m\n"
printf "\n"

# 1. Locate compatible Python (3.12+)
printf "\033[1;33m[1/6] Searching for Python 3.12+...\033[0m\n"
FOUND_PYTHON=""

for cmd in python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VERSION="$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")"
        if [ -n "$PY_VERSION" ]; then
            MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
            MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
            if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 12 ]; then
                FOUND_PYTHON="$cmd"
                printf "  \033[1;32m[OK] Found Python %s using '%s'\033[0m\n" "$PY_VERSION" "$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$FOUND_PYTHON" ]; then
    printf "\n"
    printf "  \033[1;31m[!] Error: Python 3.12 or higher was not found on your system.\033[0m\n"
    printf "  \033[1;33mPlease install Python 3.12+ using your distribution's package manager:\033[0m\n"
    printf "      Ubuntu/Debian:  sudo apt update && sudo apt install python3.12 python3.12-venv\n"
    printf "      Fedora/RHEL:    sudo dnf install python3.12\n"
    printf "      Arch Linux:     sudo pacman -S python\n"
    exit 1
fi

# 2. Virtual Environment (.venv)
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

printf "\033[1;33m[2/6] Configuring virtual environment...\033[0m\n"
if [ ! -f "$VENV_PYTHON" ]; then
    printf "  Creating virtual environment at '%s'...\n" "$VENV_DIR"
    "$FOUND_PYTHON" -m venv "$VENV_DIR"
else
    printf "  \033[1;32m[OK] Existing virtual environment detected.\033[0m\n"
fi

# 3. Install Dependencies
printf "\033[1;33m[3/6] Installing locked dependencies...\033[0m\n"
if command -v uv >/dev/null 2>&1; then
    printf "  Using uv for fast deterministic dependency installation...\n"
    uv pip sync requirements.txt --python "$VENV_PYTHON"
    uv pip install --no-deps -e . --python "$VENV_PYTHON"
else
    printf "  Using pip with cryptographic hash verification...\n"
    # Pinned bootstrap toolchain (rotate with the lockfile, verify with: pip index versions pip)
    "$VENV_PYTHON" -m pip install --quiet "pip==26.2.1"
    "$VENV_PYTHON" -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt
    "$VENV_PYTHON" -m pip install --quiet --no-deps -e .
fi
printf "  \033[1;32m[OK] Dependencies installed successfully.\033[0m\n"

# 4. Environment & Storage Configuration
printf "\033[1;33m[4/6] Verifying environment & storage directories...\033[0m\n"
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        printf "  \033[1;32m[OK] Created .env from template (.env.example).\033[0m\n"
        printf "  \033[1;33m[!] Set a strong TRACE_DATABASE_URL password and TRACE_SECRET_KEY before production use.\033[0m\n"
    fi
else
    printf "  \033[1;32m[OK] Existing .env file preserved.\033[0m\n"
fi

DEFAULT_STORAGE="${HOME}/.trace/storage"
if [ ! -d "$DEFAULT_STORAGE" ]; then
    mkdir -p "$DEFAULT_STORAGE"
    printf "  \033[1;32m[OK] Created forensic storage directory at '%s'.\033[0m\n" "$DEFAULT_STORAGE"
else
    printf "  \033[1;32m[OK] Forensic storage directory exists.\033[0m\n"
fi

# 5. Database Initialization & Schema Migrations
printf "\033[1;33m[5/6] Initializing database and running schema migrations...\033[0m\n"
if [ "${SKIP_DB_MIGRATION:-0}" != "1" ]; then
    TRACE_BIN="$VENV_DIR/bin/trace"
    if "$TRACE_BIN" db init >/dev/null 2>&1 && \
       "$TRACE_BIN" db migrate >/dev/null 2>&1; then
        printf "  \033[1;32m[OK] Database schema initialized and up to date.\033[0m\n"
    else
        printf "  \033[1;33m[!] Database connection failed or database server is offline.\033[0m\n"
        printf "      You can configure TRACE_DATABASE_URL in .env and run 'trace db init' later.\033[0m\n"
    fi
else
    printf "  Skipping database migrations as requested.\n"
fi

# 6. Expose 'trace' command globally
printf "\033[1;33m[6/6] Exposing 'trace' command to ~/.local/bin...\033[0m\n"
USER_BIN="${HOME}/.local/bin"
mkdir -p "$USER_BIN"

LAUNCHER_SCRIPT="$USER_BIN/trace"
cat <<EOF > "$LAUNCHER_SCRIPT"
#!/usr/bin/env sh
exec "$VENV_DIR/bin/trace" "\$@"
EOF
chmod +x "$LAUNCHER_SCRIPT"
printf "  \033[1;32m[OK] Installed launcher script to '%s'.\033[0m\n" "$LAUNCHER_SCRIPT"

# Check if ~/.local/bin is in PATH
PATH_INCLUDED=0
case ":$PATH:" in
    *:"$USER_BIN":*) PATH_INCLUDED=1 ;;
    *) PATH_INCLUDED=0 ;;
esac

printf "\n"
printf "\033[1;32m  ================================================================\033[0m\n"
printf "\033[1;32m              TRACE INSTALLATION COMPLETED SUCCESSFULLY!          \033[0m\n"
printf "\033[1;32m  ================================================================\033[0m\n"
printf "\n"

if [ "$PATH_INCLUDED" -eq 1 ]; then
    printf "  You can now run Trace from any terminal by typing:\n"
    printf "      \033[1;36mtrace\033[0m\n\n"
else
    printf "  \033[1;33mNote: '%s' is not in your current PATH.\033[0m\n" "$USER_BIN"
    printf "  Add it to your shell profile by running:\n"
    printf "      \033[1;36mecho 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc\033[0m (or ~/.zshrc)\n"
    printf "      \033[1;36msource ~/.bashrc\033[0m\n\n"
    printf "  Or run directly:\n"
    printf "      \033[1;36m%s/trace\033[0m\n\n" "$USER_BIN"
fi

printf "  Quick test:\n"
printf "      \033[1;36mtrace case list\033[0m\n\n"
