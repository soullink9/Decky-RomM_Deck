# Decky store

This branch is a Decky Loader plugin store, written by the release workflows (scripts/decky_store.py on the main
branch); don't edit it by hand. It lists RomM Deck's releases, downloaded from their GitHub releases, followed
by the official Decky store's plugins.

- `plugins.json`: the plugin list Decky shows. `plugins/versions.json`: what Decky checks for updates.
- `own.json`: RomM Deck's releases. `official/`: the official store's listing as last fetched.

Decky reads it through a web address that answers both `<store>` and `<store>/versions`; CONTRIBUTING.md on the
main branch explains how to serve it.
