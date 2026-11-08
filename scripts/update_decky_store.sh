#!/bin/sh
# Updates the Decky store on the repository's `store` branch (see scripts/decky_store.py), from Gitea's workflows:
#   scripts/update_decky_store.sh <tag> <zip>   release.yml: add this release, then rebuild
#   scripts/update_decky_store.sh               store.yml (on a schedule): rebuild with the official listing
#
# Reads from the environment, as the workflows set it:
#   TOKEN               a token that may push to the repository
#   GITHUB_REPOSITORY   owner/repo, and GITHUB_SERVER_URL, Gitea's address (both set by Gitea's runner)
#   GITEA_INTERNAL_URL  optional: Gitea's address as the runner reaches it (fetch and push go there)
#   GITEA_PUBLIC_URL    optional: Gitea's address as the handheld reaches it, for the download links;
#                       Gitea's own address (its ROOT_URL) when not set
#   STORE_AUTHOR_NAME, STORE_AUTHOR_EMAIL   who the store's commits are by
#
# The release and the schedule can update the store at the same moment; if the push is refused because the
# branch moved, it starts again from the new store (three tries).
set -eu

auth=$(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)
repo="${GITEA_INTERNAL_URL:-$GITHUB_SERVER_URL}/$GITHUB_REPOSITORY.git"
public="${GITEA_PUBLIC_URL:-$GITHUB_SERVER_URL}"
if [ $# -ge 2 ]; then
    message="chore(store): add $1"
else
    message="chore(store): refresh the official listing and links"
fi

for attempt in 1 2 3; do
    rm -rf store
    git init -q store
    if git -C store -c http.extraHeader="Authorization: Basic $auth" fetch -q --depth 1 "$repo" store; then
        git -C store checkout -q FETCH_HEAD
    else
        echo "No store branch yet: starting one"
    fi
    if [ $# -ge 2 ]; then
        python3 scripts/decky_store.py add store "$1" "$2" "$GITHUB_REPOSITORY"
    fi
    python3 scripts/decky_store.py build store "$public"

    git -C store add -A
    if git -C store diff --cached --quiet; then
        echo "Store unchanged"
        exit 0
    fi
    git -C store -c user.name="$STORE_AUTHOR_NAME" -c user.email="$STORE_AUTHOR_EMAIL" commit -q -m "$message"
    if git -C store -c http.extraHeader="Authorization: Basic $auth" push -q "$repo" HEAD:refs/heads/store; then
        echo "Store updated"
        exit 0
    fi
    echo "The store branch changed meanwhile (try $attempt of 3): starting again from it"
    sleep 5
done
exit 1
