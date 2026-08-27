# Releasing

The release is **not** cut by CI. `release.yml` only reads the repo: it looks for
a version in `pyproject.toml` that has no tag yet, runs the tests, publishes to
PyPI, and creates `v<version>` plus a GitHub Release.

So a release is a commit, and the commit's shape matters.

## Cutting one

1. Confirm everything is merged. A rebase merge rewrites SHAs, so
   `git branch --no-merged` reports false positives — check patch equivalence
   instead:

   ```bash
   gh pr list --state open                      # must be empty
   git cherry origin/main origin/<branch>       # no lines starting with '+'
   ```

2. Bump `version` in `pyproject.toml`. Nothing else carries the version.

3. Commit with this exact shape:

   ```
   chore(release): <X.Y.Z> — <one-line editorial title>
   ```

   The em dash is load-bearing. `docs-site/lib/changelog.ts` extracts the title
   with `^chore\(release\):\s*\d+\.\d+\.\d+\s*[—–-]\s*(.+)$`; without it the
   page falls back to "Version X.Y.Z", which works but reads like a build
   number. The Features/Fixes entries under it come from the Conventional
   Commits prefixes of the other commits in the release.

4. Open the PR titled `Release <X.Y.Z> — <description>` and merge it.

## What updates the docs site, and when

Two things happen on that merge, in parallel, and they do not wait for each
other:

| Trigger | What it does | When |
|---|---|---|
| Push to `main` | Vercel's Git integration rebuilds the docs site | ~1 min |
| Push to `main` | `release.yml` tests, publishes to PyPI, tags, creates the GitHub Release | ~3-4 min |

The docs **content** is fine either way — the `.mdx` files are in the same push,
so prose changes ship with the merge.

The **changelog** is the part that races. `/changelog` is rendered from the
GitHub Releases API, and the Vercel build finishes minutes before
`release.yml` reaches its last step and creates the release. The site is
therefore built against a release that does not exist yet.

`revalidate: 3600` means it self-corrects — but up to an hour later. So
`release.yml` ends by POSTing a Vercel Deploy Hook, which rebuilds the site once
there is actually something to read.

That step needs a repository secret:

- **`VERCEL_DEPLOY_HOOK_URL`** — create it in the Vercel dashboard under
  Project Settings → Git → Deploy Hooks (branch: `main`), then add it under
  Settings → Secrets and variables → Actions.

Without the secret the step prints why it skipped and exits 0. A fork has no
hook, and that is not a reason to fail a release that already published.

## Timing note

PyPI is published *before* the GitHub Release is created. If the workflow fails
between those two steps, the version exists on PyPI without a tag — re-running
will skip the publish (PyPI rejects a duplicate) and needs the tag created by
hand.
