# How to roll back

Every release is pinned to a commit ID (see the table in [CHANGELOG.md](CHANGELOG.md)). Commits on GitHub are
permanent, so nothing is ever lost: rolling back just makes an older version live again. Pick the option that suits you.

## Option 1: Render dashboard (fastest, no code, about 1 minute)

1. Open https://dashboard.render.com and click the **tripsentry** service.
2. Click **Events** (or **Deploys**) in the left menu. Each deploy shows its commit message and commit ID.
3. Find the version you want (match the commit ID in CHANGELOG.md), click **⋯ → Rollback** (or **Rollback to this deploy**), and confirm.
4. Check the footer of https://tripsentry.onrender.com: it shows the version that is live.

Note: the next push to GitHub deploys the newest code again. To stay on the old version, also do Option 2.

## Option 2: Make the old version the newest code on GitHub (permanent)

On a computer with git installed:

```bash
git clone https://github.com/sdaha2050/FunnelPulse.git
cd FunnelPulse
git checkout 61e87c1 -- .          # the commit ID of the version you want (v1.3.0 here)
git commit -m "Roll back to v1.3.0"
git push
```

Render deploys it automatically in 1–2 minutes. History is kept, so you can roll forward again the same way
(use the newer version's commit ID).

## Option 3: Look at or download an old version

- See a version's code: `https://github.com/sdaha2050/FunnelPulse/tree/61e87c1` (any commit ID from the changelog)
- Download it as a zip: `https://github.com/sdaha2050/FunnelPulse/archive/61e87c1.zip`
- See what changed in it: `https://github.com/sdaha2050/FunnelPulse/commit/61e87c1`
- Compare a version with today: `https://github.com/sdaha2050/FunnelPulse/compare/61e87c1...main`
- Full history: https://github.com/sdaha2050/FunnelPulse/commits/main

Optional: on GitHub you can also turn any version into a named release yourself (**Releases → Draft a new
release → Choose a tag**, type `v1.3.0`, set **Target** to its commit ID, publish).

## Option 4: Ask Claude

Say "roll back to v1.3.0" and Claude will do Option 2, run the tests, push and confirm the live site.
