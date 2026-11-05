param(
    [ValidateSet("doctor","status","sync","context","apply","test","publish")]
    [string]$Action = "doctor",

    [string]$Message = "chore: update AI-Dev-Company"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$StateDir = Join-Path $env:LOCALAPPDATA "AI-Dev-Company\GPT-GIT"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Invoke-Git {
    param([string[]]$GitArgs)

    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($GitArgs -join ' ')"
    }
}

function Get-GitOutput {
    param([string[]]$GitArgs)

    $result = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($GitArgs -join ' ')"
    }
    return ($result -join "`n")
}

switch ($Action) {

    "doctor" {
        Write-Host "`n===== GPT-GIT ENVIRONMENT =====" -ForegroundColor Cyan
        Write-Host "Repository: $RepoRoot"

        Write-Host "`n===== GIT =====" -ForegroundColor Cyan
        Invoke-Git @("--version")

        Write-Host "`n===== PYTHON =====" -ForegroundColor Cyan
        if (Get-Command python -ErrorAction SilentlyContinue) {
            Invoke-Git @("status", "-sb")
            python --version
        } else {
            Write-Warning "Python not found in PATH."
        }

        Write-Host "`n===== BRANCH =====" -ForegroundColor Cyan
        git branch --show-current

        Write-Host "`n===== REMOTE =====" -ForegroundColor Cyan
        git remote -v

        Write-Host "`n===== STATUS =====" -ForegroundColor Cyan
        Invoke-Git @("status", "-sb")

        Write-Host "`nGPT-GIT Bridge is installed." -ForegroundColor Green
    }

    "status" {
        Write-Host "`n===== PROJECT STATUS =====" -ForegroundColor Cyan
        Invoke-Git @("status", "-sb")
        Invoke-Git @("log", "-5", "--oneline", "--decorate")
    }

    "sync" {
        Write-Host "`n===== SAFE GITHUB SYNC =====" -ForegroundColor Cyan

        Invoke-Git @("fetch", "origin")

        $remoteFilesText = Get-GitOutput @(
            "ls-tree", "-r", "--name-only", "origin/main"
        )

        $remoteFiles = @(
            $remoteFilesText -split "`r?`n" |
            Where-Object { $_ }
        )

        $untracked = @(git ls-files --others --exclude-standard)

        $collisions = @(
            $untracked | Where-Object {
                $remoteFiles -contains $_
            }
        )

        if ($collisions.Count -gt 0) {
            Write-Host "File path conflicts:" -ForegroundColor Red
            $collisions | ForEach-Object { Write-Host $_ }
            throw "Resolve path collisions before syncing."
        }

        Write-Host "`nSaving local changes safely..." -ForegroundColor Cyan

        $beforeOutput = & git rev-parse --verify --quiet refs/stash 2>$null
        $beforeStash = ""
        if ($LASTEXITCODE -eq 0) {
            $beforeStash = ($beforeOutput | Out-String).Trim()
        }

        & git stash push --include-untracked -m "GPT-GIT automatic backup before sync"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not safely stash local changes."
        }

        $afterOutput = & git rev-parse --verify --quiet refs/stash 2>$null
        $afterStash = ""
        if ($LASTEXITCODE -eq 0) {
            $afterStash = ($afterOutput | Out-String).Trim()
        }

        $stashCreated = (
            ![string]::IsNullOrWhiteSpace($afterStash) -and
            $afterStash -ne $beforeStash
        )

        Write-Host "`nChecking branch history..." -ForegroundColor Cyan

        try {
            & git merge-base --is-ancestor HEAD origin/main

            if ($LASTEXITCODE -ne 0) {
                throw "Branch histories diverged. No automatic merge performed."
            }

            Invoke-Git @("merge", "--ff-only", "origin/main")
        }
        catch {
            if ($stashCreated) {
                Write-Host "Restoring local changes..." -ForegroundColor Yellow
                & git stash apply --index $afterStash

                if ($LASTEXITCODE -ne 0) {
                    Write-Host "Backup remains in Git stash: $afterStash" -ForegroundColor Red
                }
                else {
                    Write-Host "Local changes restored." -ForegroundColor Green
                }
            }

            throw
        }

        if ($stashCreated) {
            Write-Host "`nRestoring local changes..." -ForegroundColor Cyan

            & git stash apply --index $afterStash

            if ($LASTEXITCODE -ne 0) {
                throw "Restore conflict. Backup preserved in Git stash: $afterStash. Do not drop it."
            }

            $topStash = & git rev-parse --verify --quiet 'stash@{0}' 2>$null
            $topStashHash = ($topStash | Out-String).Trim()

            if ($topStashHash -eq $afterStash) {
                & git stash drop 'stash@{0}'
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "Restored successfully, but backup stash was not removed."
                }
            }

            Write-Host "All local changes restored." -ForegroundColor Green
        }

        $currentBranch = (git branch --show-current).Trim()

        if ($currentBranch -eq "development") {
            Invoke-Git @(
                "branch", "--set-upstream-to=origin/main", "development"
            )
        }

        Write-Host "`n===== SYNC COMPLETE =====" -ForegroundColor Green
        Invoke-Git @("status", "-sb")
    }
    "context" {
        $builder = [System.Text.StringBuilder]::new()

        [void]$builder.AppendLine("# AI-Dev-Company GPT Context")
        [void]$builder.AppendLine("Repository: $RepoRoot")
        [void]$builder.AppendLine("Branch: $(git branch --show-current)")
        [void]$builder.AppendLine("Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
        [void]$builder.AppendLine("")

        [void]$builder.AppendLine("## Git status")
        [void]$builder.AppendLine((Get-GitOutput @("status", "-sb")))
        [void]$builder.AppendLine("")

        [void]$builder.AppendLine("## Project files")
        $tree = Get-ChildItem -Recurse -File -Force |
            Where-Object {
                $_.FullName -notmatch '[\\/](\.git|__pycache__|\.pytest_cache|\.venv|venv|node_modules)[\\/]' -and
                $_.Extension -notin @(".sqlite3", ".db", ".pyc")
            } |
            Select-Object -First 100 |
            ForEach-Object {
                $_.FullName.Substring($RepoRoot.Length + 1)
            }

        foreach ($item in $tree) {
            [void]$builder.AppendLine("- $item")
        }

        $files = @(
            "Foundation plan",
            "README.md",
            ".gitignore",
            "AGENTS.md",
            "ai_dev_company\__init__.py",
            "ai_dev_company\memory_store.py",
            "ai_dev_company\agent_loader.py",
            "ai_dev_company\cli.py",
            "ai_dev_company\__main__.py",
            "tests\test_active_memory.py"
        )

        foreach ($file in $files) {
            if (Test-Path -LiteralPath $file -PathType Leaf) {
                [void]$builder.AppendLine("")
                [void]$builder.AppendLine("## FILE: $file")

                $content = Get-Content -LiteralPath $file -Raw
                if ($content.Length -gt 12000) {
                    $content = $content.Substring(0, 12000) +
                        "`n[TRUNCATED - request relevant section if required]"
                }

                [void]$builder.AppendLine($content)
            }
        }

        $contextPath = Join-Path $StateDir "GPT-CONTEXT.txt"
        [System.IO.File]::WriteAllText(
            $contextPath,
            $builder.ToString(),
            [System.Text.UTF8Encoding]::new($false)
        )

        Write-Host "`nContext created:" -ForegroundColor Green
        Write-Host $contextPath
        Start-Process notepad.exe -ArgumentList "`"$contextPath`""
    }

    "apply" {
        $patch = Get-Clipboard -Raw

        if ([string]::IsNullOrWhiteSpace($patch)) {
            throw "Clipboard empty. Copy GPT unified diff first."
        }

        if ($patch -notmatch '(?m)^diff --git ') {
            throw "Clipboard mein valid unified Git diff nahi mila."
        }

        $patchPath = Join-Path $StateDir "incoming.patch"
        [System.IO.File]::WriteAllText(
            $patchPath,
            $patch,
            [System.Text.UTF8Encoding]::new($false)
        )

        $backupDir = Join-Path $StateDir (
            "backups\" + (Get-Date -Format "yyyyMMdd-HHmmss")
        )

        $seen = @{}

        foreach ($line in ($patch -split "`r?`n")) {
            if ($line -match '^(---|\+\+\+)\s+(.+)$') {
                $relative = $Matches[2].Trim('"')

                if ($relative -eq "/dev/null") { continue }

                $relative = $relative -replace '^[ab]/', ''
                $segments = $relative -split '[/\\]'

                if ($relative -match '^[\\/]' -or
                    $segments -contains '..' -or
                    $relative -match ':') {
                    throw "Unsafe patch path rejected: $relative"
                }

                if ($seen.ContainsKey($relative)) { continue }
                $seen[$relative] = $true

                $source = Join-Path $RepoRoot $relative
                $fullPath = [System.IO.Path]::GetFullPath($source)
                $prefix = $RepoRoot.TrimEnd('\') + '\'

                if (!$fullPath.StartsWith(
                    $prefix,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                    throw "Patch path outside repository rejected."
                }

                if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
                    $backupPath = Join-Path $backupDir $relative
                    $backupParent = Split-Path $backupPath -Parent
                    New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
                    Copy-Item -LiteralPath $fullPath -Destination $backupPath
                }
            }
        }

        Write-Host "Checking patch..." -ForegroundColor Cyan
        Invoke-Git @("apply", "--check", "--whitespace=nowarn", $patchPath)

        Write-Host "Applying patch..." -ForegroundColor Cyan
        Invoke-Git @("apply", "--whitespace=nowarn", $patchPath)

        Write-Host "`nChanges applied successfully." -ForegroundColor Green
        Write-Host "Backup location: $backupDir"
        Invoke-Git @("status", "--short")
    }

    "test" {
        Write-Host "`n===== PYTEST =====" -ForegroundColor Cyan
        python -m pytest -q

        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed. Changes have NOT been published."
        }

        Write-Host "`nAll tests passed." -ForegroundColor Green
    }

    "publish" {
        Write-Host "Running tests before publishing..." -ForegroundColor Cyan

        python -m pytest -q
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed. Nothing published."
        }

        Invoke-Git @("fetch", "origin")

        & git merge-base --is-ancestor origin/main HEAD
        if ($LASTEXITCODE -ne 0) {
            throw "Local branch is not based on latest origin/main. Run sync first."
        }

        Invoke-Git @("add", "-A")

        $staged = @(git diff --cached --name-only)

        if ($staged.Count -eq 0) {
            Write-Host "No changes to publish." -ForegroundColor Yellow
            return
        }

        $unsafe = @($staged | Where-Object {
            ($_ -match '(^|/)\.env($|/)') -or
            ($_ -match '\.(sqlite3?|db|pem|pfx|p12)$') -or
            ($_ -match '(^|/)(id_rsa|credentials\.json)$')
        })

        if ($unsafe.Count -gt 0) {
            Write-Host "Sensitive/database files detected:" -ForegroundColor Red
            $unsafe | ForEach-Object { Write-Host $_ }
            Invoke-Git (@("reset", "--") + $unsafe)
            throw "Unsafe files unstaged. Review them before publishing."
        }

        Write-Host "`n===== FILES TO PUBLISH =====" -ForegroundColor Cyan
        $staged | ForEach-Object { Write-Host " + $_" }

        Write-Host "`n===== CHANGE SUMMARY =====" -ForegroundColor Cyan
        Invoke-Git @("diff", "--cached", "--check")
        Invoke-Git @("diff", "--cached", "--stat")

        $answer = Read-Host "`nType PUSH to commit and push these changes to GitHub main"

        if ($answer.Trim().ToUpperInvariant() -ne "PUSH") {
            Write-Host "Cancelled. Changes remain local." -ForegroundColor Yellow
            return
        }

        Invoke-Git @("commit", "-m", $Message)
        Invoke-Git @("push", "origin", "HEAD:main")

        Write-Host "`nGitHub publish successful." -ForegroundColor Green
    }
}
