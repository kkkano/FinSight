$ErrorActionPreference = 'Stop'

$frontendRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'start_wp4_browser_server.mjs'
Set-Location $frontendRoot
& node $launcher
