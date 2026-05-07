#requires -Version 7.0
[CmdletBinding()]
param(
    [string[]]$Owners = @(),
    [string[]]$Repos = @(),
    [switch]$IncludePrivate,
    [switch]$IncludeForks,
    [switch]$IncludeArchived,
    [string[]]$IncludePatterns = @("*"),
    [string[]]$ExcludePatterns = @(),
    [string[]]$LanguageAllowlist = @(),
    [string]$BranchPrefix = "chore/health-sweep",
    [string[]]$Reviewers = @(),
    [string[]]$Labels = @("maintenance", "automated", "health-sweep"),
    [int]$MaxParallel = 4,
    [switch]$DryRun,
    [bool]$SetupCI = $true,
    [bool]$SetupDependabot = $true,
    [bool]$SetupCodeQL = $true,
    [bool]$SetupPreCommit = $true,
    [bool]$UseDependabot = $true,
    [bool]$CleanOldBranches = $true,
    [bool]$CreatePR = $true,
    [bool]$Push = $true,
    [bool]$ConventionalCommits = $true,
    [bool]$SignCommits,
    [string]$ReportPath = "$PWD\repo-sweep",
    [int]$TimeoutPerRepoMinutes = 30
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Test-Prerequisite {
    $required = @('git', 'gh')
    $missing = @()
    foreach ($tool in $required) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            $missing += $tool
        }
    }
    if ($missing.Count -gt 0) {
        Write-Error "Missing required tools: $($missing -join ', '). Install them first."
        exit 1
    }
    gh auth status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "GitHub CLI not authenticated. Run: gh auth login"
        exit 1
    }
}

function Get-RepoList {
    param([string[]]$Owners, [string[]]$Repos, [bool]$IncPrivate, [bool]$IncForks, [bool]$IncArchived)
    $allRepos = @()
    if ($Repos.Count -gt 0) {
        return $Repos
    }
    foreach ($owner in $Owners) {
        $result = gh repo list $owner --limit 1000 --json name,owner,isPrivate,isFork,isArchived | ConvertFrom-Json
        foreach ($repo in $result) {
            if (-not $IncPrivate -and $repo.isPrivate) { continue }
            if (-not $IncForks -and $repo.isFork) { continue }
            if (-not $IncArchived -and $repo.isArchived) { continue }
            $fullName = '{0}/{1}' -f $repo.owner.login, $repo.name
            $allRepos += $fullName
        }
    }
    return $allRepos
}

function Test-Pattern {
    param([string]$Name, [string[]]$Include, [string[]]$Exclude)
    foreach ($ex in $Exclude) {
        if ($Name -like $ex) { return $false }
    }
    foreach ($inc in $Include) {
        if ($Name -like $inc) { return $true }
    }
    return $false
}

function Invoke-RepoSweep {
    param(
        [string]$RepoName,
        [string]$WorkDir,
        [hashtable]$Config
    )
    $startTime = Get-Date
    $report = @{
        Repo = $RepoName
        Status = 'PASS'
        StartTime = $startTime
        Steps = @()
        Changes = @()
        Vulnerabilities = @()
    }

    try {
        Set-Location $WorkDir
        $repoDir = Join-Path $WorkDir ($RepoName -replace '/', '_')

        # Clone
        Write-Output "[$RepoName] Cloning..."
        git clone "https://github.com/$RepoName.git" $repoDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
        Set-Location $repoDir

        # Get default branch
        $defaultBranch = git remote show origin | Select-String 'HEAD branch' | ForEach-Object { ($_ -split ':')[1].Trim() }
        git checkout $defaultBranch 2>&1 | Out-Null

        if ($Config.CleanOldBranches -and -not $Config.DryRun) {
            Remove-StaleBranchReference -BranchPrefix $Config.BranchPrefix
        }

        # Create sweep branch
        $branchName = "$($Config.BranchPrefix)-$(Get-Date -Format 'yyyyMMdd')"
        git checkout -b $branchName 2>&1 | Out-Null

        # Detect languages
        $languages = @()
        if (Test-Path 'package.json') { $languages += 'Node' }
        if (Test-Path 'pyproject.toml') { $languages += 'Python' }
        if (Test-Path 'requirements.txt') { $languages += 'Python' }
        if (Test-Path 'go.mod') { $languages += 'Go' }
        if (Test-Path 'Cargo.toml') { $languages += 'Rust' }
        if ((Get-ChildItem -Filter '*.csproj' -Recurse).Count -gt 0) { $languages += 'CSharp' }
        if ((Get-ChildItem -Filter '*.sln' -Recurse).Count -gt 0) { $languages += 'CSharp' }
        if (Test-Path 'pom.xml') { $languages += 'Java' }
        if (Test-Path 'build.gradle') { $languages += 'Java' }
        if (Test-Path 'composer.json') { $languages += 'PHP' }
        if (Test-Path 'Gemfile') { $languages += 'Ruby' }

        $uniqueLanguages = $languages | Sort-Object -Unique
        if ($Config.LanguageAllowlist.Count -gt 0) {
            $allowedLookup = $Config.LanguageAllowlist | ForEach-Object { $_.ToLowerInvariant() }
            $languages = $uniqueLanguages | Where-Object { $allowedLookup -contains $_.ToLowerInvariant() }
        } else {
            $languages = $uniqueLanguages
        }

        $report.Steps += @{ Step = 'Detection'; Languages = ($languages -join ', '); Status = 'OK' }

        if (-not $languages) {
            $report.Steps += @{ Step = 'LanguageFilter'; Status = 'SKIP' }
        } else {
            # Process each language
            foreach ($lang in $languages) {
                switch ($lang) {
                'Node' {
                    if (Get-Command 'corepack' -ErrorAction SilentlyContinue) {
                        corepack enable 2>&1 | Out-Null
                    }
                    if (Test-Path 'pnpm-lock.yaml') {
                        pnpm install --frozen-lockfile 2>&1 | Out-Null
                    } elseif (Test-Path 'yarn.lock') {
                        yarn install --frozen-lockfile 2>&1 | Out-Null
                    } else {
                        npm ci 2>&1 | Out-Null
                    }
                    $report.Steps += @{ Step = 'Node:Install'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }

                    if (Test-Path '.prettierrc*') {
                        npx prettier -w . 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Node:Format'; Status = 'OK' }
                    }
                    if (Test-Path '.eslintrc*') {
                        npx eslint --ext .js,.jsx,.ts,.tsx . --fix 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Node:Lint'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    if (Test-Path 'tsconfig.json') {
                        npx tsc --noEmit 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Node:TypeCheck'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    $pkgJson = Get-Content 'package.json' | ConvertFrom-Json
                    if ($pkgJson.scripts.build) {
                        npm run build 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Node:Build'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    if ($pkgJson.scripts.test) {
                        npm test 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Node:Test'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    $auditResult = npm audit --json 2>&1 | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($auditResult.metadata.vulnerabilities.high -gt 0) {
                        $report.Vulnerabilities += "Node: $($auditResult.metadata.vulnerabilities.high) high"
                        $report.Status = 'WARN'
                    }
                    $report.Steps += @{ Step = 'Node:Audit'; Status = 'OK' }
                }
                'Python' {
                    if (-not (Test-Path '.venv')) {
                        python -m venv .venv 2>&1 | Out-Null
                    }
                    & .\.venv\Scripts\Activate.ps1
                    python -m pip install -U pip --quiet 2>&1 | Out-Null
                    if (Test-Path 'pyproject.toml') {
                        pip install -e . --quiet 2>&1 | Out-Null
                    } elseif (Test-Path 'requirements.txt') {
                        pip install -r requirements.txt --quiet 2>&1 | Out-Null
                    }
                    $report.Steps += @{ Step = 'Python:Install'; Status = 'OK' }

                    if (Get-Command 'black' -ErrorAction SilentlyContinue) {
                        python -m black . 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Python:Format'; Status = 'OK' }
                    }
                    if (Get-Command 'ruff' -ErrorAction SilentlyContinue) {
                        python -m ruff check . --fix 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Python:Lint'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    if ((Test-Path 'mypy.ini') -or (Test-Path 'py.typed')) {
                        python -m mypy . 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Python:TypeCheck'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                    if (Test-Path 'tests') {
                        pytest -q 2>&1 | Out-Null
                        $report.Steps += @{ Step = 'Python:Test'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    }
                }
                'Go' {
                    go mod tidy 2>&1 | Out-Null
                    gofmt -s -w . 2>&1 | Out-Null
                    go vet ./... 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'Go:Lint'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    go test ./... 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'Go:Test'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                }
                'Rust' {
                    cargo fmt --all 2>&1 | Out-Null
                    cargo clippy -- -D warnings 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'Rust:Lint'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    cargo test 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'Rust:Test'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                }
                'CSharp' {
                    dotnet restore 2>&1 | Out-Null
                    dotnet format 2>&1 | Out-Null
                    dotnet build -c Release 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'CSharp:Build'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                    dotnet test -c Release 2>&1 | Out-Null
                    $report.Steps += @{ Step = 'CSharp:Test'; Status = if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' } }
                }
                }
            }
        }

        # Scaffold hygiene files
        if ($Config.SetupCI -or $Config.SetupPreCommit) {
            Add-HygieneContent
            $report.Changes += 'Hygiene files scaffolded'
        }

        # Add CI workflows
        if ($Config.SetupCI) {
            New-Item -ItemType Directory -Force -Path '.github/workflows' | Out-Null
            $ciContent = Get-CITemplate -Languages $languages
            Set-Content -Path '.github/workflows/ci.yml' -Value $ciContent
            $report.Changes += 'CI workflow added'
        }

        if ($Config.SetupCodeQL) {
            $codeQlContent = Get-CodeQLTemplate -Languages $languages
            if ($codeQlContent) {
                New-Item -ItemType Directory -Force -Path '.github/workflows' | Out-Null
                Set-Content -Path '.github/workflows/codeql.yml' -Value $codeQlContent
                $report.Changes += 'CodeQL workflow added'
            }
        }

        if ($Config.SetupDependabot -and $Config.UseDependabot) {
            $depContent = Get-DependabotTemplate -Languages $languages
            Set-Content -Path '.github/dependabot.yml' -Value $depContent
            $report.Changes += 'Dependabot config added'
        }

        if ($Config.SetupPreCommit) {
            $preCommitContent = Get-PreCommitTemplate -Languages $languages
            Set-Content -Path '.pre-commit-config.yaml' -Value $preCommitContent
            $report.Changes += 'Pre-commit config added'
        }

        # Check for changes
        $gitStatus = git status --porcelain
        if ($gitStatus) {
            if ($Config.ConventionalCommits) {
                git add -A 2>&1 | Out-Null
                $commitArgs = @('commit', '-m', 'chore(ci): add health sweep automation and hygiene files')
                if ($Config.SignCommits) {
                    $commitArgs = @('commit', '-S', '-m', 'chore(ci): add health sweep automation and hygiene files')
                }
                & git @commitArgs 2>&1 | Out-Null
                $report.Changes += 'Committed changes'
            }

            if ($Config.Push -and -not $Config.DryRun) {
                git push -u origin $branchName 2>&1 | Out-Null
                $report.Changes += 'Pushed branch'

                if ($Config.CreatePR) {
                    $prBody = "Automated repository health sweep`n`n"
                    $prBody += "## Changes`n"
                    $prBody += ($report.Changes -join "`n- ")
                    $prBody += "`n`n## Status`n"
                    foreach ($step in $report.Steps) {
                        $prBody += "- $($step.Step): $($step.Status)`n"
                    }

                    $prTitle = "Health sweep $(Get-Date -Format 'yyyy-MM-dd')"
                    $ghArgs = @('pr', 'create', '-B', $defaultBranch, '-H', $branchName, '-t', $prTitle, '-b', $prBody)
                    foreach ($label in $Config.Labels) {
                        $ghArgs += @('--label', $label)
                    }
                    foreach ($reviewer in $Config.Reviewers) {
                        $ghArgs += @('--reviewer', $reviewer)
                    }

                    & gh @ghArgs 2>&1 | Out-Null
                    $report.Changes += 'PR created'
                }
            }
        } else {
            $report.Status = 'SKIP'
            $report.Changes += 'No changes needed'
        }

    } catch {
        $report.Status = 'FAIL'
        $report.Steps += @{ Step = 'Error'; Status = $_.Exception.Message }
    } finally {
        $report.EndTime = Get-Date
        $report.Duration = ($report.EndTime - $report.StartTime).TotalSeconds
    }

    return $report
}

function Remove-StaleBranchReference {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$BranchPrefix,
        [int]$RetentionDays = 30
    )

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    $pattern = 'refs/remotes/origin/{0}*' -f $BranchPrefix
    $branchRefs = git for-each-ref --format='%(refname:short)|%(committerdate:iso8601)' $pattern
    foreach ($ref in $branchRefs) {
        if (-not $ref) { continue }
        $parts = $ref -split '\|'
        if ($parts.Count -lt 2) { continue }
        $branchName = $parts[0] -replace '^origin/'
        try {
            $commitDate = [datetime]::Parse($parts[1])
        } catch {
            continue
        }

        if ($commitDate -lt $cutoff) {
            $target = "origin/$branchName"
            if ($PSCmdlet.ShouldProcess($target, 'Delete stale branch')) {
                try {
                    git push origin --delete $branchName 2>&1 | Out-Null
                } catch {
                    $message = 'Failed to delete stale branch {0}: {1}' -f $branchName, $_.Exception.Message
                    Write-Warning $message
                }
            }
        }
    }
}

function Add-HygieneContent {
    param()

    if (-not (Test-Path '.gitignore')) {
        $gitignoreContent = @"
# Dependencies
node_modules/
.venv/
venv/
__pycache__/
*.pyc
target/
bin/
obj/

# Build outputs
dist/
build/
*.dll
*.exe

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db
"@
        Set-Content -Path '.gitignore' -Value $gitignoreContent
    }

    if (-not (Test-Path '.editorconfig')) {
        $editorConfig = @"
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2
"@
        Set-Content -Path '.editorconfig' -Value $editorConfig
    }

    if (-not (Test-Path 'LICENSE')) {
        $license = $env:SWEEP_LICENSE ?? 'MIT'
        if ($license -eq 'MIT') {
            $mitContent = @"
MIT License

Copyright (c) $(Get-Date -Format yyyy)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
"@
            Set-Content -Path 'LICENSE' -Value $mitContent
        }
    }

    if (-not (Test-Path 'SECURITY.md')) {
        $secContent = @"
# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities to the maintainers privately.
"@
        Set-Content -Path 'SECURITY.md' -Value $secContent
    }
}

function Get-CITemplate {
    param([string[]]$Languages)
    $languageComment = if ($Languages) {
        '# Languages: ' + (($Languages | Sort-Object -Unique | ForEach-Object { $_.ToLowerInvariant() }) -join ', ')
    } else {
        '# Languages: auto-detected'
    }

    return @"
$languageComment
name: CI

on:
  push:
    branches: [main, master, develop]
  pull_request:
    branches: [main, master, develop]

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18, 20]
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: `${{ matrix.node-version }}
          cache: npm
      - run: npm ci
      - run: npm run build --if-present
      - run: npm test
"@
}

function Get-DependabotTemplate {
    param([string[]]$Languages)
    $languageSet = $Languages | Sort-Object -Unique
    $updates = @(
        [pscustomobject]@{
            Ecosystem = 'github-actions'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly',
                '    open-pull-requests-limit: 5'
            )
        }
    )

    if ($languageSet -contains 'Node') {
        $updates += [pscustomobject]@{
            Ecosystem = 'npm'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly',
                '    open-pull-requests-limit: 10',
                '    versioning-strategy: increase'
            )
        }
    }
    if ($languageSet -contains 'Python') {
        $updates += [pscustomobject]@{
            Ecosystem = 'pip'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly'
            )
        }
    }
    if ($languageSet -contains 'Go') {
        $updates += [pscustomobject]@{
            Ecosystem = 'gomod'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly'
            )
        }
    }
    if ($languageSet -contains 'Rust') {
        $updates += [pscustomobject]@{
            Ecosystem = 'cargo'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly'
            )
        }
    }
    if ($languageSet -contains 'CSharp') {
        $updates += [pscustomobject]@{
            Ecosystem = 'nuget'
            Directory = '/'
            Settings = @(
                '    schedule:',
                '      interval: weekly'
            )
        }
    }

    $yamlLines = @('version: 2', 'updates:')
    foreach ($update in $updates) {
        $yamlLines += "  - package-ecosystem: $($update.Ecosystem)"
        $yamlLines += "    directory: $($update.Directory)"
        $yamlLines += $update.Settings
        $yamlLines += ''
    }

    return ($yamlLines -join "`n").TrimEnd()
}

function Get-CodeQLTemplate {
    param([string[]]$Languages)

    $languageMap = [ordered]@{
        Node   = 'javascript-typescript'
        Python = 'python'
        Go     = 'go'
        CSharp = 'csharp'
        Java   = 'java'
    }

    $codeqlLanguages = $Languages | ForEach-Object {
        if ($languageMap.Contains($_)) {
            $languageMap[$_]
        }
    } | Sort-Object -Unique

    if (-not $codeqlLanguages) {
        return $null
    }

    $languageListDisplay = $codeqlLanguages -join ', '
    $languageListYaml = ($codeqlLanguages | ForEach-Object { "'$_'" }) -join ', '

    return @"
name: CodeQL

on:
  push:
    branches: [main, master, develop]
  pull_request:
    branches: [main, master, develop]
  schedule:
    - cron: '0 8 * * 1'

jobs:
  analyze:
    name: Analyze ($languageListDisplay)
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write
    strategy:
      matrix:
        language: [$languageListYaml]
    steps:
      - uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: $${{ matrix.language }}
      - name: Autobuild
        uses: github/codeql-action/autobuild@v3
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3
"@
}

function Get-PreCommitTemplate {
    param([string[]]$Languages)
    $languageSet = $Languages | Sort-Object -Unique
    $lines = @(
        'repos:',
        '  - repo: https://github.com/pre-commit/pre-commit-hooks',
        '    rev: v4.5.0',
        '    hooks:',
        '      - id: trailing-whitespace',
        '      - id: end-of-file-fixer',
        '      - id: check-yaml',
        '      - id: check-json',
        '      - id: check-added-large-files',
        "        args: ['--maxkb=1000']",
        '      - id: check-merge-conflict',
        '      - id: detect-private-key',
        '      - id: mixed-line-ending'
    )

    if ($languageSet -contains 'Python') {
        $lines += ''
        $lines += '  - repo: https://github.com/psf/black'
        $lines += '    rev: 24.1.1'
        $lines += '    hooks:'
        $lines += '      - id: black'
        $lines += '        language_version: python3.11'
        $lines += ''
        $lines += '  - repo: https://github.com/charliermarsh/ruff-pre-commit'
        $lines += '    rev: v0.2.0'
        $lines += '    hooks:'
        $lines += '      - id: ruff'
        $lines += '        args: [--fix, --exit-non-zero-on-fix]'
    }

    if ($languageSet -contains 'Node') {
        $lines += ''
        $lines += '  - repo: https://github.com/pre-commit/mirrors-prettier'
        $lines += '    rev: v4.0.0-alpha.8'
        $lines += '    hooks:'
        $lines += '      - id: prettier'
        $lines += '        types_or: [javascript, jsx, ts, tsx, json, yaml, markdown]'
        $lines += ''
        $lines += '  - repo: https://github.com/pre-commit/mirrors-eslint'
        $lines += '    rev: v9.0.0-beta.1'
        $lines += '    hooks:'
        $lines += '      - id: eslint'
        $lines += '        files: \\.(js|ts|jsx|tsx)$'
        $lines += '        types: [file]'
        $lines += '        additional_dependencies:'
        $lines += '          - eslint@8.56.0'
    }

    if ($languageSet -contains 'Rust') {
        $lines += ' '
        $lines += '  - repo: https://github.com/doublify/pre-commit-rust'
        $lines += '    rev: v1.0'
        $lines += '    hooks:'
        $lines += '      - id: fmt'
        $lines += '      - id: cargo-check'
        $lines += '      - id: clippy'
    }

    if ($languageSet -contains 'Go') {
        $lines += ' '
        $lines += '  - repo: https://github.com/dnephin/pre-commit-golang'
        $lines += '    rev: v0.5.1'
        $lines += '    hooks:'
        $lines += '      - id: go-fmt'
        $lines += '      - id: go-vet'
        $lines += '      - id: go-mod-tidy'
    }

    return ($lines -join "`n").TrimEnd()
}

# Main execution
Test-Prerequisite

if (-not (Test-Path $ReportPath)) {
    New-Item -ItemType Directory -Path $ReportPath | Out-Null
}

$repos = Get-RepoList -Owners $Owners -Repos $Repos -IncPrivate:$IncludePrivate -IncForks:$IncludeForks -IncArchived:$IncludeArchived
$repos = $repos | Where-Object { Test-Pattern -Name $_ -Include $IncludePatterns -Exclude $ExcludePatterns }

Write-Output "Processing $($repos.Count) repositories..."

$config = @{
    BranchPrefix = $BranchPrefix
    Reviewers = $Reviewers
    Labels = $Labels
    LanguageAllowlist = $LanguageAllowlist
    SetupCI = $SetupCI
    SetupDependabot = $SetupDependabot
    SetupCodeQL = $SetupCodeQL
    SetupPreCommit = $SetupPreCommit
    UseDependabot = $UseDependabot
    CleanOldBranches = $CleanOldBranches
    Push = $Push
    CreatePR = $CreatePR
    ConventionalCommits = $ConventionalCommits
    DryRun = $DryRun
    SignCommits = $SignCommits
    TimeoutPerRepoMinutes = $TimeoutPerRepoMinutes
}

$results = $repos | ForEach-Object -Parallel {
    $repoName = $_
    $workDir = Join-Path $using:ReportPath "work_$($repoName -replace '/', '_')"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    $report = & $using:MyInvocation.MyCommand.ScriptBlock Invoke-RepoSweep -RepoName $repoName -WorkDir $workDir -Config $using:config
    $report
} -ThrottleLimit $MaxParallel -TimeoutSeconds ($TimeoutPerRepoMinutes * 60)

# Generate aggregate report
$aggregateReport = "# Repository Fleet Health Sweep Report`n`n"
$aggregateReport += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n`n"
$aggregateReport += "## Summary`n`n"
$aggregateReport += "| Repository | Status | Duration | Changes |`n"
$aggregateReport += "|-----------|--------|----------|---------|`n"
foreach ($result in $results) {
    $aggregateReport += "| $($result.Repo) | $($result.Status) | $([math]::Round($result.Duration, 2))s | $($result.Changes.Count) |`n"
}
$aggregateReport += "`n## Details`n`n"
foreach ($result in $results) {
    $aggregateReport += "### $($result.Repo)`n`n"
    $aggregateReport += "**Status:** $($result.Status)`n`n"
    $aggregateReport += "**Steps:**`n"
    foreach ($step in $result.Steps) {
        $aggregateReport += "- $($step.Step): $($step.Status)`n"
    }
    $aggregateReport += "`n**Changes:**`n"
    foreach ($change in $result.Changes) {
        $aggregateReport += "- $change`n"
    }
    $aggregateReport += "`n"
}

Set-Content -Path (Join-Path $ReportPath 'SWEEP-REPORT.md') -Value $aggregateReport
Write-Output "`nReport saved to: $(Join-Path $ReportPath 'SWEEP-REPORT.md')"

$failCount = ($results | Where-Object { $_.Status -eq 'FAIL' }).Count
if ($failCount -gt 0) {
    Write-Error "$failCount repositories failed"
    exit 1
}

exit 0
