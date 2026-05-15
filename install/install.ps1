# Install script for Claude MATSim Toolkit on Windows (PowerShell)
# Usage: ./install/install.ps1

$ErrorActionPreference = "Stop"

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$ClaudeDir = Join-Path $HOME ".claude"
$SkillsDst = Join-Path $ClaudeDir "skills\transport-modeling"
$HooksDst  = Join-Path $ClaudeDir "hooks"

Write-Host "Installing Claude MATSim Toolkit..." -ForegroundColor Cyan
Write-Host "  Repo:   $RepoRoot"
Write-Host "  Target: $ClaudeDir"
Write-Host ""

# 1. Copy skill
Write-Host "[1/3] Copying skill -> $SkillsDst" -ForegroundColor Yellow
if (Test-Path $SkillsDst) {
    Write-Host "      Existing skill found. Backup -> ${SkillsDst}.bak"
    if (Test-Path "${SkillsDst}.bak") { Remove-Item -Recurse -Force "${SkillsDst}.bak" }
    Move-Item $SkillsDst "${SkillsDst}.bak"
}
$SkillsSrc = Join-Path $RepoRoot "skills\transport-modeling"
Copy-Item -Recurse $SkillsSrc $SkillsDst
Write-Host "      OK"

# 2. Copy hook
Write-Host "[2/3] Copying hook -> $HooksDst" -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $HooksDst | Out-Null
$HookSrc = Join-Path $RepoRoot "hooks\validate_matsim.py"
Copy-Item -Force $HookSrc (Join-Path $HooksDst "validate_matsim.py")
Write-Host "      OK"

# 3. Print settings snippet
Write-Host ""
Write-Host "[3/3] Register the hook in ~/.claude/settings.json" -ForegroundColor Yellow
Write-Host ""
Write-Host "Add this 'hooks' section to your settings.json:" -ForegroundColor Green
Write-Host ""
$HookPathForJson = (Join-Path $HooksDst "validate_matsim.py").Replace("\", "/")
$snippet = @"
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python $HookPathForJson",
            "timeout": 15
          }
        ]
      }
    ]
  }
"@
Write-Host $snippet
Write-Host ""
Write-Host "Done. Restart Claude Code to pick up changes." -ForegroundColor Cyan
