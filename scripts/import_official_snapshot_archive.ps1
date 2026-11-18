param(
    [Parameter(Mandatory = $true)]
    [string]$ArchivePath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedArchive = (Resolve-Path -LiteralPath $ArchivePath).Path
$rawTarget = Join-Path $repoRoot "data/raw/sporttery/2026-11-18"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-snapshot-" + [guid]::NewGuid().ToString("N"))

if (Test-Path -LiteralPath $rawTarget) {
    throw "目标目录已存在，拒绝覆盖原始快照：$rawTarget"
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    Expand-Archive -LiteralPath $resolvedArchive -DestinationPath $tempRoot
    $snapshotRoot = Join-Path $tempRoot "dlt_official_raw"
    if (-not (Test-Path -LiteralPath $snapshotRoot -PathType Container)) {
        throw "ZIP 内未找到 dlt_official_raw/ 目录"
    }

    $jsonFiles = @(Get-ChildItem -LiteralPath $snapshotRoot -File -Filter "page-*.json" |
        Where-Object { $_.Name -notlike "*.manifest.json" })
    $sidecars = @(Get-ChildItem -LiteralPath $snapshotRoot -File -Filter "page-*.manifest.json")
    $collection = @(Get-ChildItem -LiteralPath $snapshotRoot -File -Filter "collection-*.manifest.json")

    if ($jsonFiles.Count -ne 30 -or $sidecars.Count -ne 30 -or $collection.Count -ne 1) {
        throw "归档结构不符合预期：page JSON=$($jsonFiles.Count), sidecar=$($sidecars.Count), collection manifest=$($collection.Count)"
    }

    $collectionData = Get-Content -LiteralPath $collection[0].FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($collectionData.total_pages -ne 30 -or $collectionData.total_records -ne 2949) {
        throw "collection manifest 的总页数/记录数与已审计快照不符"
    }

    New-Item -ItemType Directory -Path $rawTarget -Force | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $snapshotRoot -File) {
        Copy-Item -LiteralPath $file.FullName -Destination $rawTarget
    }

    $python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "未找到 Windows Python Launcher (py)。原始快照已复制到 $rawTarget；安装 Python 3 后可重新运行离线导入命令。"
    }

    Push-Location $repoRoot
    try {
        & py -3 scripts/fetch_history.py --snapshots-dir $rawTarget --require-manifests --output "data/processed/draws-20261118.jsonl"
        if ($LASTEXITCODE -ne 0) {
            throw "离线导入失败，退出码：$LASTEXITCODE。原始快照已保留，不会删除。"
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "完成。原始快照：$rawTarget"
    Write-Host "请检查 data/processed/draws-20261118.jsonl 及其 manifest。"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
