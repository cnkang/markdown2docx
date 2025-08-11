#!/usr/bin/env bash
set -e

# Install Python dependencies using uv, allowing additional arguments (e.g., --group dev)
uv sync "$@"

# Ensure pandoc is installed
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Pandoc not found. Attempting to install..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y pandoc
  elif command -v brew >/dev/null 2>&1; then
    brew install pandoc
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y pandoc
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y pandoc
  elif command -v pacman >/dev/null 2>&1; then
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Pandoc not found. Attempting to install..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y pandoc || { echo "Failed to install pandoc using apt-get"; exit 1; }
  elif command -v brew >/dev/null 2>&1; then
    brew install pandoc || { echo "Failed to install pandoc using brew"; exit 1; }
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y pandoc || { echo "Failed to install pandoc using yum"; exit 1; }
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y pandoc || { echo "Failed to install pandoc using dnf"; exit 1; }
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm pandoc || { echo "Failed to install pandoc using pacman"; exit 1; }
  else
    echo "Could not determine package manager. Please install pandoc manually."
    exit 1
  else
    echo "Could not determine package manager. Please install pandoc manually."
    exit 1
  fi
else
  echo "Pandoc already installed."
fi
