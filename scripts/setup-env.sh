#!/usr/bin/env bash
set -e

# Install Python dependencies using uv, allowing additional arguments (e.g., --group dev)
uv sync "$@"

# Ensure pandoc is installed
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Pandoc not found. Attempting to install..."
  
  # Check if sudo is available for package managers that need it
  has_sudo() {
    command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null
  }
  
  if command -v brew >/dev/null 2>&1; then
    brew install pandoc || { echo "Failed to install pandoc using brew"; exit 1; }
  elif command -v apt-get >/dev/null 2>&1; then
    if has_sudo; then
      sudo apt-get update && sudo apt-get install -y pandoc || { echo "Failed to install pandoc using apt-get"; exit 1; }
    else
      echo "sudo required for apt-get. Please install pandoc manually: sudo apt-get install pandoc"
      exit 1
    fi
  elif command -v yum >/dev/null 2>&1; then
    if has_sudo; then
      sudo yum install -y pandoc || { echo "Failed to install pandoc using yum"; exit 1; }
    else
      echo "sudo required for yum. Please install pandoc manually: sudo yum install pandoc"
      exit 1
    fi
  elif command -v dnf >/dev/null 2>&1; then
    if has_sudo; then
      sudo dnf install -y pandoc || { echo "Failed to install pandoc using dnf"; exit 1; }
    else
      echo "sudo required for dnf. Please install pandoc manually: sudo dnf install pandoc"
      exit 1
    fi
  elif command -v pacman >/dev/null 2>&1; then
    if has_sudo; then
      sudo pacman -Sy --noconfirm pandoc || { echo "Failed to install pandoc using pacman"; exit 1; }
    else
      echo "sudo required for pacman. Please install pandoc manually: sudo pacman -S pandoc"
      exit 1
    fi
  else
    echo "Could not determine package manager. Please install pandoc manually from: https://pandoc.org/installing.html"
    exit 1
  fi
else
  echo "Pandoc already installed."
fi
