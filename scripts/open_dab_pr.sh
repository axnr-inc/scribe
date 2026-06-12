#!/usr/bin/env bash
# Open a leaderboard PR against ucbepic/DataAgentBench with our SCRIBE submission.
#
# PREREQS (do these first if they are not already done):
#   1. `gh auth status`  — must be logged in to github.com.
#      If not:  `gh auth login`  (scopes: repo, workflow are enough).
#   2. Make sure the submission artifacts exist:
#        submissions/scribe_actioneer_opus47.json
#        submissions/AGENT_DESCRIPTION.md
#        submissions/PR_DESCRIPTION.md
#      If runs 1-4 weren't complete when you built the JSON, re-run:
#        python3 scripts/build_dab_submission.py [--include-patents]
#
# WHAT THIS DOES:
#   - Forks ucbepic/DataAgentBench to your GitHub account (if not already forked).
#   - Clones the fork to /tmp/dab_fork (fresh clone every time).
#   - Copies the submission JSON into  submissions/scribe_actioneer_opus47.json
#     and the agent description into  submissions/scribe_actioneer_opus47.md
#     (filename convention matches existing PRs under submissions/, e.g.
#      react_gpt-5.2.json, promptql_opus46_wiki4_pp2_n5.json).
#   - Creates branch  scribe-actioneer-opus47-submission, commits, pushes.
#   - Opens a PR against ucbepic/DataAgentBench:main with the body taken from
#     submissions/PR_DESCRIPTION.md.
#
# This script does NOT modify the SCRIBE repo. All work happens in /tmp/dab_fork.

set -euo pipefail

UPSTREAM_REPO="ucbepic/DataAgentBench"
FORK_DIR="/tmp/dab_fork"
BRANCH="scribe-actioneer-opus47-submission"
SCRIBE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SUBMISSION_JSON="$SCRIBE_ROOT/submissions/scribe_actioneer_opus47.json"
AGENT_DESC_MD="$SCRIBE_ROOT/submissions/AGENT_DESCRIPTION.md"
PR_BODY_MD="$SCRIBE_ROOT/submissions/PR_DESCRIPTION.md"

# Destination filenames inside the fork (under submissions/).
DEST_JSON_NAME="scribe_actioneer_opus47.json"
DEST_MD_NAME="scribe_actioneer_opus47.md"

# --- preflight ---
for f in "$SUBMISSION_JSON" "$AGENT_DESC_MD" "$PR_BODY_MD"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: required artifact missing: $f" >&2
    exit 1
  fi
done

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: 'gh' CLI is not installed." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

GH_USER="$(gh api user --jq .login)"
FORK_REPO="$GH_USER/DataAgentBench"
echo "GitHub user: $GH_USER"
echo "Will fork $UPSTREAM_REPO -> $FORK_REPO"

# --- fork (idempotent) ---
if gh repo view "$FORK_REPO" >/dev/null 2>&1; then
  echo "Fork $FORK_REPO already exists; skipping fork."
else
  gh repo fork "$UPSTREAM_REPO" --clone=false
fi

# --- fresh clone of the fork ---
rm -rf "$FORK_DIR"
git clone "https://github.com/$FORK_REPO.git" "$FORK_DIR"
cd "$FORK_DIR"

# Make sure fork's main is up to date with upstream main.
git remote add upstream "https://github.com/$UPSTREAM_REPO.git"
git fetch upstream main
git checkout main
git merge --ff-only upstream/main || {
  echo "WARN: fork main is not fast-forwardable from upstream; continuing on current main." >&2
}
git push origin main || true

# --- branch + copy in artifacts ---
git checkout -b "$BRANCH"
mkdir -p submissions
cp "$SUBMISSION_JSON" "submissions/$DEST_JSON_NAME"
cp "$AGENT_DESC_MD"   "submissions/$DEST_MD_NAME"
# Integrity artifacts: self-audit ledger + full 270-trial trace bundle.
cp "$SCRIBE_ROOT/submissions/taint.json"          "submissions/scribe_actioneer_opus47_taint.json"
cp "$SCRIBE_ROOT/submissions/scribe_traces.zip"   "submissions/scribe_actioneer_opus47_traces.zip"

git add "submissions/$DEST_JSON_NAME" "submissions/$DEST_MD_NAME" \
        "submissions/scribe_actioneer_opus47_taint.json" \
        "submissions/scribe_actioneer_opus47_traces.zip"
git commit -m "[Leaderboard] SCRIBE (Actioneer) - Claude Opus 4.7 - 83.87% Pass@1"

git push -u origin "$BRANCH"

# --- open PR ---
gh pr create \
  --repo "$UPSTREAM_REPO" \
  --base main \
  --head "$GH_USER:$BRANCH" \
  --title "[Leaderboard] SCRIBE (Actioneer) - Claude Opus 4.7 - 83.87% Pass@1" \
  --body-file "$PR_BODY_MD"

echo ""
echo "PR opened. Review it on github.com/$UPSTREAM_REPO/pulls"
