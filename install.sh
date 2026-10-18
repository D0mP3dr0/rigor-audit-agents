#!/usr/bin/env bash
# Install the rigor-audit agents, campaign skills and tools into a project's .claude/ folder.
# Usage: ./install.sh /path/to/project
set -euo pipefail
src="$(cd "$(dirname "$0")" && pwd)"
dest="${1:?usage: install.sh /path/to/project}"
mkdir -p "$dest/.claude/agents" "$dest/.claude/skills" "$dest/.claude/audit-tools"
cp "$src"/agents/*.md "$dest/.claude/agents/"
cp -r "$src"/skills/* "$dest/.claude/skills/"
cp "$src"/tools/*.py "$dest/.claude/audit-tools/"
echo "installed into $dest/.claude (agents, skills, audit-tools)"
