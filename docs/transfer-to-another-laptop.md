# Moving the repository to another laptop and opening the pull request

## What you receive

| File | What it is |
|---|---|
| `Final_Project-Bazinga-.bundle` | the whole Git repository (all branches, all commits) in one file — preferred |
| `Final_Project-Bazinga--with-git.zip` | the project folder including `.git`; `.venv`, `stores/` and caches left out |

Use either. Both carry the full history. A ZIP made by GitHub's "Download ZIP" or by `git archive`
would not: those drop `.git`, which is the history. Never rebuild `.git` by running `git init` on
copied files; that throws away every commit.

## The one thing to understand first

The original project came as a GitHub ZIP of commit `2ffe22a`, without its history. Here it was
committed as `ac9abc8`: same files, different hash, no shared ancestor with GitHub.
If you push this branch to the original GitHub repository as-is, GitHub sees unrelated histories
and the pull request cannot be opened. So on the second laptop you replay the 11 DevOps commits on
top of the real `2ffe22a`. Because `ac9abc8` and `2ffe22a` have identical file trees, the replay
applies without conflicts.

## Steps on the second laptop

Needs: Git 2.30+, your GitHub account signed in on that laptop.

```bash
# 1. Clone the real repository (contains the baseline 2ffe22a)
git clone https://github.com/<owner>/Final_Project-Bazinga-.git
cd Final_Project-Bazinga-
git cat-file -t 2ffe22a857d4a5637c5d247518773280722ae9e9     # must print: commit

# 2. Bring in the DevOps branch from the bundle (or from the unzipped folder's path)
git bundle verify /path/to/Final_Project-Bazinga-.bundle
git fetch /path/to/Final_Project-Bazinga-.bundle devops-improvements:devops-local
#   from the ZIP instead:  git fetch /path/to/unzipped/Final_Project-Bazinga- devops-improvements:devops-local

# 3. Replay the DevOps commits onto the real baseline
git rebase --onto 2ffe22a857d4a5637c5d247518773280722ae9e9 \
               ac9abc84e541532176e0e04a3c82de5672dc2751 devops-local
git branch -m devops-local devops-improvements

# 4. Check before pushing
git log --oneline 2ffe22a..devops-improvements                 # the 11 DevOps commits, oldest at the bottom
git merge-base --is-ancestor 2ffe22a devops-improvements && echo "baseline is an ancestor"
git diff --stat 2ffe22a devops-improvements | tail -1          # ~65 files changed
git status                                                     # clean

# 5. Push the branch (this is the only publishing step, and you run it)
git push -u origin devops-improvements
```

`git rebase` keeps each commit's author and author date (when the work was done) and sets the
committer date to the time you run it. That is the normal, truthful record of a replay.

If `main` on GitHub has moved past `2ffe22a` since the ZIP was downloaded, step 3 still works;
the PR will show any new `main` commits as already in the base. If it reports conflicts, stop and
check what changed on `main` before resolving.

## Open the pull request (one)

GitHub → repository → **Compare & pull request** for `devops-improvements` → base `main` →
title e.g. "DevOps: container, Kubernetes, CI/CD, release control, observability, security" →
body: paste `docs/submission-summary.md` (or link to it) → **Create pull request**.
CI runs on the PR. Check the four jobs; that run is the first build on `python:3.12-slim` and the
first trivy scan (`docs/verification.md`, BLOCKED items).

Or with the GitHub CLI: `gh pr create --base main --head devops-improvements --fill`.

## Pushing to a new, empty repository instead

No replay needed; the baseline commit in that repository will be `ac9abc8`:

```bash
git clone /path/to/Final_Project-Bazinga-.bundle Final_Project-Bazinga-
cd Final_Project-Bazinga-
git remote set-url origin https://github.com/<you>/<new-repo>.git
git push -u origin main devops-improvements
```

Then the baseline URL is `https://github.com/<you>/<new-repo>/commit/ac9abc84e541532176e0e04a3c82de5672dc2751`,
and `docs/baseline-submission.md` must say so.

## Remote configuration in the received repository

The repository as delivered has no remote configured (`git remote -v` prints nothing). Nothing
points at a server, so nothing can be pushed by accident before you set one.

## After the push

- Release: `git tag -a v1.0.0 -m "v1.0.0" && git push origin v1.0.0` → `release.yml` publishes
  `ghcr.io/<owner>/reasoning-engine:1.0.0`. Make the package public in GitHub → Packages if a
  cluster without credentials must pull it.
- Local run on the new laptop: `bash setup.sh` (venv, deps, stores) or `docker build` per README.
  `.venv/` and `stores/` are not transferred; they are rebuilt.
