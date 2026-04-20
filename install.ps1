# One-shot installer for Windows volunteers (PowerShell 5+ / 7+).
#
# PS> iwr -useb https://raw.githubusercontent.com/bulgariamitko/bg-izbori-monitor/main/install.ps1 | iex
#
# Installs git, Python 3.12, ffmpeg, yt-dlp, gh (via winget), authenticates
# gh, forks+clones the repo, sets up venv, starts `contribute.py --loop`.

$ErrorActionPreference = "Stop"
$Repo     = "bulgariamitko/bg-izbori-monitor"
$LocalDir = Join-Path $env:USERPROFILE "bg-izbori-monitor"

function Say([string]$msg)  { Write-Host "» $msg" -ForegroundColor Cyan }
function Warn([string]$msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }
function Have([string]$cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Require-Winget {
    if (-not (Have winget)) {
        Fail "winget is required. Install 'App Installer' from the Microsoft Store, then re-run this script."
    }
}

function Install-Deps {
    Require-Winget
    $targets = @(
        @{ id = "Git.Git";               bin = "git"    }
        @{ id = "Python.Python.3.12";    bin = "python" }
        @{ id = "Gyan.FFmpeg";           bin = "ffmpeg" }
        @{ id = "yt-dlp.yt-dlp";         bin = "yt-dlp" }
        @{ id = "GitHub.cli";            bin = "gh"     }
    )
    foreach ($t in $targets) {
        if (Have $t.bin) { continue }
        Say "winget install $($t.id)"
        winget install --id $t.id --silent --accept-source-agreements --accept-package-agreements | Out-Null
    }
    # ensure PATH picks up newly-installed tools
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

function Ensure-Gh-Auth {
    $probe = gh auth status 2>$null
    if ($LASTEXITCODE -eq 0) { Say "GitHub CLI already logged in"; return }
    Say "Logging into GitHub (browser will open)"
    Warn "No GitHub account yet? The login page has a 'Sign up' link."
    gh auth login --git-protocol https --web --hostname github.com
}

function Fork-And-Clone {
    if (Test-Path (Join-Path $LocalDir ".git")) {
        Say "Repo already at $LocalDir — hard-syncing with upstream"
        # Ensure upstream remote exists (older installs may be missing it).
        git -C $LocalDir remote add upstream "https://github.com/$Repo.git" 2>$null | Out-Null
        git -C $LocalDir fetch upstream main
        git -C $LocalDir checkout main 2>$null | Out-Null
        git -C $LocalDir reset --hard upstream/main
        return
    }
    Say "Forking $Repo and cloning to $LocalDir"
    gh repo fork $Repo --clone=$false --default-branch-only 2>$null | Out-Null
    $user = (gh api user --jq .login).Trim()
    git clone "https://github.com/$user/bg-izbori-monitor.git" $LocalDir
    git -C $LocalDir remote add upstream "https://github.com/$Repo.git" 2>$null | Out-Null
    git -C $LocalDir fetch upstream
    git -C $LocalDir reset --hard upstream/main
    git -C $LocalDir config pull.rebase true
}

function Setup-Venv {
    Set-Location $LocalDir
    if (-not (Test-Path "venv")) {
        Say "Creating Python venv"
        python -m venv venv
    }
    & .\venv\Scripts\Activate.ps1
    Say "Installing Python deps"
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
}

function Announce-Cf {
    Warn "IMPORTANT: Open https://evideo.bg/ once in Chrome so Cloudflare"
    Warn "gives your browser a cookie — yt-dlp reuses it."
    Read-Host "Press Enter once you've opened evideo.bg in Chrome"
}

function Run-Contribute {
    Set-Location $LocalDir
    & .\venv\Scripts\Activate.ps1
    $gh = (gh api user --jq .login).Trim()
    Say "Starting transcription loop as '$gh' — Ctrl-C to stop"
    # Outer loop: pull latest upstream code + data BEFORE every iteration so
    # long-running volunteers pick up config / sections changes mid-session.
    while ($true) {
        Say "Sync with upstream (latest code + sections)…"
        git fetch upstream main 2>$null | Out-Null
        git checkout main 2>$null | Out-Null
        git reset --hard upstream/main 2>$null | Out-Null
        pip install --quiet -r requirements.txt 2>$null | Out-Null
        try {
            python contribute.py --gh-handle $gh
        } catch {
            Warn "contribute.py errored — retrying in 30s"
            Start-Sleep -Seconds 30
        }
        Start-Sleep -Seconds 5
    }
}

Install-Deps
Ensure-Gh-Auth
Fork-And-Clone
Setup-Venv
Announce-Cf
Run-Contribute
