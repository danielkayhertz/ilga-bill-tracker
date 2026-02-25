# IL Bill Tracker

A single-file web app for tracking Illinois General Assembly bills — with shared notes, real-time ILGA stage monitoring, and a GitHub-backed data store. No server required.

![Screenshot of IL Bill Tracker showing bill cards with stage badges](https://github.com/user-attachments/assets/placeholder)

---

## What it does

- **Tracks bills** from ILGA.gov — stage (In Committee / Passed / Signed / Failed), sponsor, last action, upcoming hearings
- **Shared notes** — annotate any bill; notes sync to GitHub so your whole team sees them
- **Add bills** — look up any bill number live from ILGA.gov and add it with one click
- **Daily auto-update** — a GitHub Actions workflow runs at 8am CT and refreshes all tracked bill statuses
- **No server** — everything is a static file hosted on GitHub Pages; bill data lives in JSON files in your repo

---

## Setup (~5 minutes)

### 1. Fork this repo

Click **Fork** at the top right of this page. Keep it public (required for GitHub Pages on free accounts).

### 2. Enable GitHub Pages

1. Go to your fork → **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Branch: `main`, Folder: `/ (root)`
4. Click **Save**

GitHub will show you the Pages URL (e.g. `https://yourname.github.io/ilga-bill-tracker`). It may take ~1 minute to go live.

### 3. Create a fine-grained Personal Access Token

1. Go to [GitHub → Settings → Personal Access Tokens (fine-grained)](https://github.com/settings/personal-access-tokens/new)
2. Under **Repository access**, select **Only select repositories** and choose your fork
3. Under **Permissions → Repository permissions**, set **Contents** to **Read and write**
4. Generate the token and copy it

> **Security note:** Fine-grained tokens are scoped to one repo and one permission. Even if someone sees your token, they can only read/write files in your bill tracker repo.

### 4. Open the tracker and complete setup

Open your GitHub Pages URL. You'll see a **Connect to GitHub** setup modal asking for:

- **GitHub Username or Organization** — your GitHub username (or org name if you forked under an org)
- **Repository Name** — `ilga-bill-tracker` (or whatever you renamed it)
- **Personal Access Token** — the token you just created

Click **Save & Connect**. The app verifies the token against the repo and stores it in your browser's `localStorage`. You're in.

### 5. Add your first bill

Click **+ Add Bill**, type a bill number (e.g. `HB1234`), click **Look up on ILGA**, fill in a title, and click **Add Bill**. The bill is saved to `user-bills.json` in your repo.

---

## Team sharing

Each team member repeats steps 3–4 with the same repo. Everyone can use their own token (each generates one with the same scopes), or share one token (less ideal but works fine for small teams).

Notes are shared — when one person saves a note, everyone sees it on their next page load.

---

## Pre-loading a fixed bill list

To track a fixed set of bills (useful if you want ILGA auto-updates for specific bills regardless of who adds them via the UI), edit `scripts/update_bill_status.py` and add entries to the `BILLS` list:

```python
BILLS = [
    {
        "billNumber": "HB1234",
        "title": "My Housing Bill",
        "year": [2026],
        "status": "Not passed into law",
        "category": "Housing",
        "url": "https://www.ilga.gov/Legislation/BillStatus?DocNum=1234&GAID=18&DocTypeID=HB&SessionID=114"
    },
    # add more...
]
```

Bills in `BILLS` are written to `bills.json` by the daily workflow. Bills added via the UI go to `user-bills.json`. Both are merged and displayed in the tracker.

---

## Daily auto-update

The GitHub Actions workflow in `.github/workflows/update-bills.yml` runs daily at 8am CT and updates ILGA data for all tracked bills (both pre-loaded and user-added). It uses the built-in `GITHUB_TOKEN` — no additional secrets needed.

To enable it:
1. Go to your fork → **Actions**
2. If prompted, click **I understand my workflows, go ahead and enable them**
3. The workflow will run automatically each day, or you can trigger it manually via **Run workflow**

---

## Customizing categories

The **Category** dropdown in the Add Bill form can be customized by editing the `<select id="add-bill-category">` options in `index.html`.

---

## Data files

| File | Contents |
|------|----------|
| `data/bills.json` | Pre-loaded bills with ILGA data (written by the Actions workflow) |
| `data/user-bills.json` | Bills added via the UI |
| `data/notes.json` | Shared notes keyed by bill number |

All three files are committed to the repo. `bills.json` is fetched publicly (no auth needed). `user-bills.json` and `notes.json` are written via the GitHub API using your Personal Access Token.

---

## Resetting

To start fresh: edit `data/bills.json`, `data/user-bills.json`, and `data/notes.json` in GitHub and set them back to `[]`, `[]`, and `{}` respectively. Then clear your browser's localStorage (DevTools → Application → Local Storage → delete `gh_config`) and reload.
