param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-PreferredDoc {
    param(
        [string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        $fullPath = Join-Path $repoRoot $candidate
        if (Test-Path $fullPath) {
            return $fullPath
        }
    }

    return $null
}

function Get-CurrentVersion {
    param(
        [string]$Text
    )

    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match "当前版本" -and $line -match "v(?<version>\d+\.\d+\.\d+)") {
            return "v{0}" -f $Matches["version"]
        }
    }

    return ""
}

function Get-VersionFromPyproject {
    $pyprojectPath = Join-Path $repoRoot "pyproject.toml"
    if (-not (Test-Path $pyprojectPath)) {
        return ""
    }

    foreach ($line in Get-Content $pyprojectPath -Encoding UTF8) {
        if ($line -match 'version\s*=\s*"(?<version>\d+\.\d+\.\d+)"') {
            return "v{0}" -f $Matches["version"]
        }
    }

    return ""
}

function Get-RecentDevlogTitle {
    param(
        [string]$Path
    )

    if (-not $Path) {
        return ""
    }

    foreach ($line in Get-Content $Path -Encoding UTF8) {
        if ($line -match '^##\s+') {
            return $line.Trim()
        }
    }

    return ""
}

function Get-FirstNonEmptyLines {
    param(
        [string]$Path,
        [int]$Count = 12
    )

    if (-not $Path) {
        return @()
    }

    $lines = Get-Content $Path -Encoding UTF8 |
        Where-Object { $_.Trim() -ne "" } |
        Select-Object -First $Count |
        ForEach-Object { [string]$_ }

    return @($lines)
}

$contextDoc = Get-PreferredDoc -Candidates @("CLAUDE.md", "AGENTS.md")
$agentsDoc = Get-PreferredDoc -Candidates @("AGENTS.md")
$readmeDoc = Get-PreferredDoc -Candidates @("README.md")
$devlogDoc = Get-PreferredDoc -Candidates @("DEVLOG.md")

$contextPreview = Get-FirstNonEmptyLines -Path $contextDoc -Count 14
$agentsPreview = Get-FirstNonEmptyLines -Path $agentsDoc -Count 14
$readmePreview = Get-FirstNonEmptyLines -Path $readmeDoc -Count 10
$versionSource = if ($contextDoc) { Get-Content $contextDoc -Encoding UTF8 -Raw } else { "" }
$version = Get-CurrentVersion -Text $versionSource
$recentDevlog = Get-RecentDevlogTitle -Path $devlogDoc
if ($recentDevlog -match "v(?<version>\d+\.\d+\.\d+)") {
    $version = "v{0}" -f $Matches["version"]
}
if (-not $version) {
    $version = Get-VersionFromPyproject
}

$result = [ordered]@{
    workspace = $repoRoot
    context_doc = $contextDoc
    agents_doc = $agentsDoc
    readme_doc = $readmeDoc
    devlog_doc = $devlogDoc
    version = $version
    recent_devlog = $recentDevlog
    context_preview = $contextPreview
    agents_preview = $agentsPreview
    readme_preview = $readmePreview
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
    exit 0
}

Write-Output "[newup] feedgrab project context"
Write-Output "workspace: $repoRoot"
if ($version) {
    Write-Output "version: $version"
}
if ($contextDoc) {
    Write-Output "context-doc: $contextDoc"
}
if ($agentsDoc) {
    Write-Output "agents-doc: $agentsDoc"
}
if ($readmeDoc) {
    Write-Output "readme-doc: $readmeDoc"
}
if ($devlogDoc) {
    Write-Output "devlog-doc: $devlogDoc"
}
if ($recentDevlog) {
    Write-Output "recent-devlog: $recentDevlog"
}

Write-Output ""
Write-Output "[context-preview]"
foreach ($line in $contextPreview) {
    Write-Output $line
}

Write-Output ""
Write-Output "[agents-preview]"
foreach ($line in $agentsPreview) {
    Write-Output $line
}

Write-Output ""
Write-Output "[readme-preview]"
foreach ($line in $readmePreview) {
    Write-Output $line
}
