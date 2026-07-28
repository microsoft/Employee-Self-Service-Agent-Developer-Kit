#!/usr/bin/env bash
#
# Monorepo-root convenience forwarder for the ESS NextGen Migration Toolkit.
#
# Lets you drive the toolkit from the very top of the repository, e.g.:
#   ./mtk.sh start --dev
#   ./mtk.sh refresh
#
# It forwards to tools/ess-nextgen-migration-toolkit/scripts/mtk.sh, which
# implicitly changes into the toolkit directory before doing anything. All logic
# lives there; this file only forwards arguments. This repo-root forwarder is
# the single entrypoint — there is no separate toolkit-root forwarder.
exec "$(dirname "$0")/tools/ess-nextgen-migration-toolkit/scripts/mtk.sh" "$@"
