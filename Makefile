# Production operations on the server (wrappers around deploy/deploy.sh; see docs/runbook.md).
#   make deploy TAG=v1.2.3      make deploy TAG=v1.2.3 DRY_RUN=1
#   make rollback               make rollback WITH_DATA=1
#   make status | history | logs | logs-follow | backup | restore FILE=...
# Add YES=1 to skip confirmation prompts (CI or scripted runs).

DEPLOY := deploy/deploy.sh
FLAGS := $(if $(DRY_RUN),--dry-run) $(if $(YES),--yes)

.PHONY: help deploy rollback status history logs logs-follow backup restore migrate-legacy update-scripts lint-deploy

help:
	@sed -n '1,5p' Makefile | sed 's/^# \{0,1\}//'

deploy:
	@$(DEPLOY) deploy $(TAG) $(FLAGS)

rollback:
	@$(DEPLOY) rollback $(FLAGS) $(if $(WITH_DATA),--with-data)

status:
	@$(DEPLOY) status

history:
	@$(DEPLOY) history

logs:
	@$(DEPLOY) logs

logs-follow:
	@$(DEPLOY) logs -f

backup:
	@$(DEPLOY) backup $(FLAGS)

restore:
	@test -n "$(FILE)" || { echo "usage: make restore FILE=.deploy/backups/conduit-data-....tar.gz"; exit 1; }
	@$(DEPLOY) restore $(FILE) $(FLAGS)

migrate-legacy:
	@$(DEPLOY) migrate-legacy $(FLAGS)

# Refresh the deploy scripts and compose files from git (the image itself comes from GHCR)
update-scripts:
	git pull --ff-only

lint-deploy:
	docker run --rm -v "$(CURDIR):/mnt:ro" koalaman/shellcheck:stable -S warning /mnt/deploy/deploy.sh
