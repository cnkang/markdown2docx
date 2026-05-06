#!/usr/bin/env bash
set -e

# Check if 'uv' is installed
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is not installed or not found in your PATH."
  echo "Please install 'uv' by following instructions at https://github.com/astral-sh/uv or run:"
  echo "  pip install uv"
  exit 1
fi

# Install Python dependencies using uv, allowing additional arguments (e.g., --group dev)
uv sync "$@"

# Ensure pandoc is installed
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Pandoc not found. Attempting to install..."
  
  # Check if sudo is available for package managers that need it
  has_sudo() {
    command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null
  }
  
  if brew_bin="$(command -v brew)"; then
    "$brew_bin" install pandoc || { echo "Failed to install pandoc using brew"; exit 1; }
  elif apt_get_bin="$(command -v apt-get)"; then
    if has_sudo; then
      sudo "$apt_get_bin" update && sudo "$apt_get_bin" install -y pandoc || { echo "Failed to install pandoc using apt-get"; exit 1; }
    else
      echo "sudo required for apt-get. Please install pandoc manually: sudo apt-get install pandoc"
      exit 1
    fi
  elif yum_bin="$(command -v yum)"; then
    if has_sudo; then
      sudo "$yum_bin" install -y pandoc || { echo "Failed to install pandoc using yum"; exit 1; }
    else
      echo "sudo required for yum. Please install pandoc manually: sudo yum install pandoc"
      exit 1
    fi
  elif dnf_bin="$(command -v dnf)"; then
    if has_sudo; then
      sudo "$dnf_bin" install -y pandoc || { echo "Failed to install pandoc using dnf"; exit 1; }
    else
      echo "sudo required for dnf. Please install pandoc manually: sudo dnf install pandoc"
      exit 1
    fi
  elif pacman_bin="$(command -v pacman)"; then
    if has_sudo; then
      sudo "$pacman_bin" -Sy --noconfirm pandoc || { echo "Failed to install pandoc using pacman"; exit 1; }
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
