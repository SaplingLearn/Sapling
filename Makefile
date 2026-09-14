# Sapling — repo-level entry points.
#
# E2E stack (#384): one command to boot / tear down the whole local test stack —
# Supabase (rootless Podman or Docker) → migrations → seed → uvicorn backend →
# test-profile Next production build — health-checked end to end.
# See docs/local-supabase.md ("One-command E2E stack").
#
# E2E exploration (#399): boot that stack, hand a Playwright-MCP-armed Claude
# agent the explorer prompt, then run the oracle CLI. See docs/e2e-exploration.md.
#
# Staging -> production promotion (#516): preflight, migrate prod, confirm,
# merge main->production, wait for the deploy, smoke. One prompt, at the merge.
# See backend/promotion/README.md.

.PHONY: e2e-up e2e-down explore explore-down gallery-shots promote

e2e-up:
	scripts/e2e-up.sh

e2e-down:
	scripts/e2e-down.sh

# Capture the /gallery product screenshots (local only; takes the stack lock).
gallery-shots:
	scripts/gallery-shots.sh

explore:
	scripts/explore.sh

explore-down:
	scripts/explore.sh down

promote:
	cd backend && venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion $(ARGS)
