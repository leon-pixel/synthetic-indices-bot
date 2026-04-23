#!/usr/bin/env bash
# Usage: ./scripts/remote_add_origin.sh YOUR_GITHUB_USERNAME [REPO_NAME]
# Example: ./scripts/remote_add_origin.sh jsmith synthetic-indices-bot
set -euo pipefail
user="${1:?Usage: $0 <github_username> [repo_name]}"
name="${2:-synthetic-indices-bot}"
url="https://github.com/${user}/${name}.git"
if git remote get-url origin &>/dev/null; then
  echo "Remote 'origin' already exists: $(git remote get-url origin)"
  echo "To replace: git remote remove origin && $0 $*"
  exit 1
fi
git remote add origin "$url"
echo "Added origin: $url"
echo "Next: git push -u origin main"
