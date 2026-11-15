#!/bin/sh
# Updates the Decky store on the repository's `store` branch (see scripts/decky_store.py), from Gitea's workflows:
#   scripts/update_decky_store.sh <tag> <zip>   release.yml: add this release, then rebuild
#   scripts/update_decky_store.sh               store.yml (on a schedule): rebuild with the official listing
#
# Reads from the environment, as the workflows set it:
#   TOKEN               a token that may push to the repository
#   GITHUB_REPOSITORY   owner/repo, and GITHUB_SERVER_URL, Gitea's address (both set by Gitea's runner)
#   PUBLIC_REPOSITORY   owner/repo on GitHub: every address in the store is GitHub's (the store branch is
#                       push-mirrored there, so it never names Gitea), and a release is listed once GitHub has it
#   LOCAL_GITEA_URL     optional: Gitea's address as the runner reaches it (fetch and push go there)
#   STORE_AUTHOR_NAME, STORE_AUTHOR_EMAIL   who the store's commits are by
#
# The branch is always one commit with no history: each update replaces it (a force push), so an address
# that was once written there doesn't stay in old commits, on Gitea or on the GitHub mirror (which follows
# force pushes). A branch that still has history is replaced at the next run even with nothing new.
# The release and the schedule can update the store at the same moment: the push only replaces the branch
# it started from, and if the branch moved meanwhile it starts again from the new store (three tries).
set -eu

auth=$(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)
repo="${LOCAL_GITEA_URL:-$GITHUB_SERVER_URL}/$GITHUB_REPOSITORY.git"
if [ $# -ge 2 ]; then
    message="chore(store): add $1"
else
    message="chore(store): refresh the official listing and links"
fi

for attempt in 1 2 3; do
    rm -rf store
    git init -q store
    old="" old_tree="" has_history=""
    if git -C store -c http.extraHeader="Authorization: Basic $auth" fetch -q --depth 1 "$repo" store; then
        git -C store checkout -q FETCH_HEAD
        old=$(git -C store rev-parse FETCH_HEAD)
        old_tree=$(git -C store rev-parse 'FETCH_HEAD^{tree}')
        # (a shallow fetch hides the parents from git log, but the commit itself still names them)
        if git -C store cat-file -p "$old" | grep -q '^parent '; then has_history=yes; fi
    else
        echo "No store branch yet: starting one"
    fi
    if [ $# -ge 2 ]; then
        python3 scripts/decky_store.py add store "$1" "$2" "$PUBLIC_REPOSITORY"
    fi
    python3 scripts/decky_store.py build store "$PUBLIC_REPOSITORY"

    git -C store add -A
    tree=$(git -C store write-tree)
    if [ "$tree" = "$old_tree" ] && [ -z "$has_history" ]; then
        echo "Store unchanged"
        exit 0
    fi
    [ -n "$has_history" ] && echo "Replacing the store branch's history with a single commit"
    commit=$(echo "$message" | git -C store -c user.name="$STORE_AUTHOR_NAME" -c user.email="$STORE_AUTHOR_EMAIL" \
        commit-tree "$tree")
    if git -C store -c http.extraHeader="Authorization: Basic $auth" push -q \
        --force-with-lease="refs/heads/store:$old" "$repo" "$commit:refs/heads/store"; then
        echo "Store updated"
        exit 0
    fi
    echo "The store branch changed meanwhile (try $attempt of 3): starting again from it"
    sleep 5
done
exit 1
