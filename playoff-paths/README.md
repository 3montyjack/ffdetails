# Playoff Path Board

Static March Madness–style playoff odds + “what you need” paths for **Should’ve kept Watson** (Sleeper `1399822865787809792`).

## Local preview

```bash
cd playoff-paths
python3 -m http.server 8765 --bind 127.0.0.1
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## GitHub Pages

Workflow: `.github/workflows/playoff-paths-pages.yml` deploys this folder on pushes to `main` (path filter) or via **Actions → Deploy playoff-paths to GitHub Pages → Run workflow**.

After the first successful deploy, the site URL is:

`https://3montyjack.github.io/ffdetails/`

### One-time enable (if Pages isn’t on yet)

1. Repo **Settings → Pages**
2. **Build and deployment → Source**: GitHub Actions
3. Merge this branch / run the workflow
4. Note: this repository is **private**. Public Pages for private repos needs GitHub Pro (or make the repo public / use an internal Pages visibility your plan allows).

## Data

`data.json` is a precomputed Monte Carlo snapshot (W1–9 scoring engine, 80k sims, weeks 11–14). Refresh by re-running the sim script and replacing the file.

## Live URL

- Board: https://3montyjack.github.io/ffdetails/playoff-paths/
- Root https://3montyjack.github.io/ffdetails/ redirects there while Pages is on **Deploy from a branch / (root)**.
- Preferred later: Settings → Pages → Source **GitHub Actions** (workflow uploads `playoff-paths/` as the site root).
