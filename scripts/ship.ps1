param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Run-Git {
    param(
        [string[]]$Arguments
    )

    $previousXdgConfigHome = $env:XDG_CONFIG_HOME
    $env:XDG_CONFIG_HOME = $repoRoot

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "git"
        $psi.Arguments = (($Arguments | ForEach-Object {
            if ($_ -match '\s|"') {
                '"' + ($_ -replace '"', '\"') + '"'
            }
            else {
                $_
            }
        }) -join ' ')
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $psi
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()

        $output = @()
        if ($stdout) {
            $output = $stdout -split "`r?`n" | Where-Object { $_ -ne "" }
        }
    }
    finally {
        $env:XDG_CONFIG_HOME = $previousXdgConfigHome
    }

    $exitCode = $process.ExitCode
    if ($stderr -and $exitCode -ne 0) {
        $output += $stderr -split "`r?`n" | Where-Object { $_ -ne "" }
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output)
    }
}

Push-Location $repoRoot
try {
    $status = Run-Git -Arguments @("status", "--short")
    $diffStat = Run-Git -Arguments @("diff", "--stat")
}
finally {
    Pop-Location
}

$requiredDocs = @("DEVLOG.md", "CLAUDE.md", "README.md", "README_EN.md")
$docStates = foreach ($doc in $requiredDocs) {
    $fullPath = Join-Path $repoRoot $doc
    [pscustomobject]@{
        path = $doc
        exists = $(Test-Path $fullPath)
    }
}

$result = [ordered]@{
    workspace = $repoRoot
    git_status_ok = ($status.ExitCode -eq 0)
    git_diff_stat_ok = ($diffStat.ExitCode -eq 0)
    git_status = $status.Output
    git_diff_stat = $diffStat.Output
    required_docs = $docStates
    next_actions = @(
        "Confirm the feature is finished and tested",
        "Update the top entry in DEVLOG.md",
        "Sync CLAUDE.md project notes with the latest code",
        "Sync README.md and README_EN.md if needed",
        "Review git diff before commit and push"
    )
}

if ($Json) {
    $result | ConvertTo-Json -Depth 5
    exit 0
}

Write-Output "[ship] release readiness"
Write-Output "workspace: $repoRoot"
Write-Output ""
Write-Output "[required-docs]"
foreach ($doc in $docStates) {
    if ($doc.exists) {
        $flag = "OK"
    }
    else {
        $flag = "MISSING"
    }
    Write-Output "$flag $($doc.path)"
}

Write-Output ""
Write-Output "[git-status --short]"
foreach ($line in $status.Output) {
    Write-Output $line
}

Write-Output ""
Write-Output "[git-diff --stat]"
foreach ($line in $diffStat.Output) {
    Write-Output $line
}

Write-Output ""
Write-Output "[next-actions]"
foreach ($item in $result.next_actions) {
    Write-Output "- $item"
}
