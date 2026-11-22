# Changelog

Every version is a **git tag** (`v1.2.0`, `v1.3.0`, ...) on GitHub. To go back to one, see [ROLLBACK.md](ROLLBACK.md).
The version running live is shown at the bottom of the app and at `/api/version`.

| Version | Date | What changed | Commit |
| --- | --- | --- | --- |
| **v1.4.1** | 2026-11-22 | Version history: tags for every release, this changelog, rollback guide, version shown in the app | (this release) |
| **v1.4.0** | 2026-11-22 | Search by order ID in "Needs a human"; new **Traveler journey** tab (enter a user ID, see search → booked for each session) | `fc8cf12` |
| **v1.3.0** | 2026-11-22 | **Live pipeline** diagram replaces the agent chat; clickstream data now lands **10–20s late** (`INGEST_DELAY`); evals split end-to-end vs agent reaction time | `61e87c1` |
| **v1.2.0** | 2026-11-21 | **Monthly + top issues** tab: 12-month simulated history, top 10 issues with root cause, fix, owner | `85c9987` |
| **v1.1.1** | 2026-11-21 | Browser no longer caches the old page after a deploy | `b066cf9` |
| **v1.1.0** | 2026-11-21 | **US by state** and **International** dashboards; California and UK problems | `9ad5e07` |
| **v1.0.2** | 2026-11-21 | Live Render URL added to README and docs | `be6b8ff` |
| **v1.0.1** | 2026-11-21 | First Render deploy (Deploy button points at the repo) | `8e46646` |
| **v1.0.0** | 2026-11-21 | First version: 8 agents, guardrails, evals, live funnel, human approval queue | `4d415b2` |

## How versions are numbered

- **Major** (`v2.0.0`): a big change in how the demo works.
- **Minor** (`v1.3.0`): a new tab or feature.
- **Patch** (`v1.1.1`): a small fix.
