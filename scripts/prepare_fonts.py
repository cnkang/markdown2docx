#!/usr/bin/env python3
"""Prepare all verified fixture fonts before the offline test phase."""

from markdown2docx.fonts import FontResolver

resolver = FontResolver()
for key in resolver.manifest["fonts"]:
    resolver.resolve(key)
print(f"Prepared {len(resolver.selected)} verified fonts")
