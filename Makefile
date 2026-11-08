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
#
# Database backup (Trov #114): pg_dump (custom format, schema + data) of one
# environment into the gitignored backups/. `make promote` takes the same dump
# of production automatically before migrating. See backend/promotion/README.md.

.PHONY: e2e-up e2e-down explore explore-down gallery-shots promote backup-db

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

# make backup-db ENV=<staging|prod|local>. prod/staging read SUPABASE_DB_URL
# from the same env file `make promote` / the db/ scripts use; local is the
# local Supabase stack's fixed DB (scripts/local-db-reset.sh; SUPABASE_DB_PORT
# as in scripts/e2e-up.sh), never .env, so ENV=local cannot dump a remote.
backup-db:
	@case "$(ENV)" in \
	  prod) cd backend && venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion.backup --env prod ;; \
	  staging) cd backend && venv/bin/dotenv -f .env.staging run -- venv/bin/python -m promotion.backup --env staging ;; \
	  local) cd backend && SUPABASE_DB_URL="postgresql://postgres:postgres@127.0.0.1:$${SUPABASE_DB_PORT:-54322}/postgres" venv/bin/python -m promotion.backup --env local ;; \
	  *) echo "usage: make backup-db ENV=<staging|prod|local>" >&2; exit 2 ;; \
	esac
