# Create the GitHub repository and push (one-time)

Your project is already a **local Git** repo on `main` with an initial commit. You only need to create the empty repo on GitHub and **push** (this environment could not run `gh` or `brew install` for you).

## Option A — GitHub website + `git` (no GitHub CLI)

1. In a browser, open GitHub and click **New repository**.
2. Set **Repository name** to: `synthetic-indices-bot` (or another name; then use that name in the URL below).
3. Choose **Public** (or Private if you prefer).
4. **Do not** add a README, .gitignore, or license (this repo already has them).
5. Create the repository. GitHub will show you commands. Use these from **your project folder** (the one that contains `README.md` and `sidx/`):

```bash
cd /path/to/synthetic-indices-bot

# If you have not added a remote yet (check with: git remote -v)
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/synthetic-indices-bot.git

# Push main branch
git push -u origin main
```

Replace `YOUR_GITHUB_USERNAME` with your GitHub username or org.

6. If GitHub asks for credentials, use a **Personal Access Token** (classic) with `repo` scope, or use GitHub’s recommended **gh auth login** / **SSH** setup.

## Option B — GitHub CLI (`gh`)

If you have [GitHub CLI](https://cli.github.com/) installed and logged in:

```bash
cd /path/to/synthetic-indices-bot
gh repo create synthetic-indices-bot --public --source=. --remote=origin --push
```

## After the first push

- Share the clone URL: `https://github.com/YOUR_GITHUB_USERNAME/synthetic-indices-bot.git`
- Update any docs that still say `YOUR_USERNAME` in [README.md](README.md) and [GETTING_STARTED.md](GETTING_STARTED.md) if you want them to show your real URL.
- Ongoing work: branch → PR → merge (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## If `git init` failed on your machine with “Operation not permitted” (hooks)

Some macOS setups block creating `.git/hooks` in certain directories. A workaround that still lets you work and push is:

```bash
cd /path/to/synthetic-indices-bot
rm -rf .git
git init --separate-git-dir /path/you/can/write/sidx-dot-git -b main
# ... add, commit, add remote, push as above
```

Or clone this repo from GitHub **after** the first successful push: you will get a normal `.git` folder.
