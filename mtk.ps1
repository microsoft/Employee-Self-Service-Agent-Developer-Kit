#requires -Version 5.1
# Monorepo-root convenience forwarder for the ESS NextGen Migration Toolkit.
#
# Lets you drive the toolkit from the very top of the repository, e.g.:
#   .\mtk.ps1 run -Dev
#   .\mtk.ps1 run -Mode writeback
#
# It forwards to tools\ess-nextgen-migration-toolkit\scripts\mtk.ps1, which
# implicitly changes into the toolkit directory before doing anything. All logic
# lives there; this file only forwards arguments.
& (Join-Path $PSScriptRoot "tools\ess-nextgen-migration-toolkit\scripts\mtk.ps1") @args
exit $LASTEXITCODE
