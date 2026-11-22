# How to roll back

Every release is saved as a git tag (see [CHANGELOG.md](CHANGELOG.md)). Nothing is ever lost: rolling back just
makes an older version live again. Pick the option that suits you.

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
git checkout v1.3.0 -- .          # replace v1.3.0 with the version you want
git commit -m "Roll back to v1.3.0"
git push
```

Render deploys it automatically in 1–2 minutes. History is kept, so you can roll forward again the same way
(for example `git checkout v1.4.1 -- .`).

## Option 3: Look at or download an old version

- See all versions: https://github.com/sdaha2050/FunnelPulse/tags
- Each tag has **zip** and **tar.gz** download links with the full code of that version.
- Compare two versions: `https://github.com/sdaha2050/FunnelPulse/compare/v1.3.0...v1.4.1`

## Option 4: Ask Claude

Say "roll back to v1.3.0" and Claude will do Option 2, run the tests, push and confirm the live site.
