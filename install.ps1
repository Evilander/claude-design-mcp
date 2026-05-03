# claude-design-mcp · one-shot Windows install
# Usage: powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Render]

param(
    [switch]$Render,
    [switch]$Editable
)

$ErrorActionPreference = "Stop"

Write-Host "[claude-design-mcp] Installing..." -ForegroundColor Cyan

$pkg = if ($Render) { ".[render]" } else { "." }
$flag = if ($Editable) { "-e" } else { "" }

if ($Editable) {
    pip install -e $pkg
} else {
    pip install $pkg
}

if ($Render) {
    Write-Host "[claude-design-mcp] Installing Chromium for Playwright..." -ForegroundColor Cyan
    playwright install chromium
}

Write-Host "[claude-design-mcp] Verifying..." -ForegroundColor Cyan
claude-design-mcp --check
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    Write-Host ""
    Write-Host "[claude-design-mcp] Setup checks failed. Set ANTHROPIC_API_KEY and re-run --check." -ForegroundColor Yellow
    exit $rc
}

Write-Host ""
Write-Host "[claude-design-mcp] Done. Wire it up in ~/.claude/settings.json:" -ForegroundColor Green
Write-Host "  see claude_desktop_config.example.json"
