# 백업 스크립트 — multirole-web 소스 + 문서 + (선택) auth.json
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\backup.ps1
#   powershell ... -File .\tools\backup.ps1 -Version 1.4.1 -AuthFile D:\rea-out\_tmp\auth.json
#
# 규칙
#   · 소스 ZIP 에는 **비밀값을 넣지 않는다**: _web_token.txt / front.json / NAS-ACCESS.md / auth.json
#   · auth.json 은 ZIP 밖에 `_backups\<ver>\auth.json` 로만 보관한다(로컬 백업 전용, git/릴리스 제외)
#   · ZIP 은 폴더 구조를 유지한다(Compress-Archive 의 평탄화 문제 회피 → ZipFile.CreateFromDirectory)

param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Version = "",
    [string]$AuthFile = "",
    [string]$OutDir = "D:\rea-out\multirole\_backups",
    [string]$TempDir = "D:\rea-out\_tmp"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path

if (-not $Version) {
    $init = Get-Content (Join-Path $Root "App\__init__.py") -Raw
    if ($init -match 'VERSION\s*=\s*"([^"]+)"') { $Version = $Matches[1] } else { throw "버전을 찾을 수 없습니다(App/__init__.py)" }
}

$bk = Join-Path $OutDir ("v" + $Version)
$stage = Join-Path $TempDir ("mrw-src-v" + ($Version -replace '\.', ''))
Remove-Item $bk -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $bk, $stage -Force | Out-Null

# 1) 스테이징 (비밀값·산출물 제외)
$skip = @("_web_token.txt", "front.json", "auth.json", "NAS-ACCESS.md")
$files = Get-ChildItem $Root -Recurse -File | Where-Object {
    $_.FullName -notmatch "\\__pycache__\\|\\\.git\\|\\_backups\\|\\logs\\" -and ($_.Name -notin $skip)
}
foreach ($f in $files) {
    $dst = Join-Path $stage $f.FullName.Substring($Root.Length + 1)
    New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
    Copy-Item $f.FullName $dst -Force
}

# 2) ZIP (구조 유지)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = Join-Path $bk ("multirole-web-src-v" + $Version + ".zip")
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

# 3) 문서 사본
foreach ($d in "README.md", "CHANGELOG.md", "MANUAL-room-rules.md", "PLAYER-GUIDE.md", "UPGRADE.md") {
    $p = Join-Path $Root $d
    if (Test-Path $p) { Copy-Item $p $bk -Force }
}

# 4) auth.json — ZIP 밖(로컬 백업 전용)
if ($AuthFile -and (Test-Path $AuthFile)) {
    Copy-Item $AuthFile (Join-Path $bk "auth.json") -Force
    Write-Host ("  auth.json 보관: {0}" -f (Join-Path $bk "auth.json"))
} else {
    Write-Host "  auth.json 없음(계정 미생성 또는 -AuthFile 미지정) → 백업에는 생략"
}

# 5) SHA256
$lines = @()
foreach ($f in (Get-ChildItem $bk -File | Where-Object { $_.Name -ne "SHA256.txt" })) {
    $lines += ("{0}  {1}" -f (Get-FileHash $f.FullName -Algorithm SHA256).Hash, $f.Name)
}
$lines | Set-Content (Join-Path $bk "SHA256.txt") -Encoding UTF8

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

$zipInfo = Get-Item $zip
$count = (Get-ChildItem $bk -File).Count
Write-Host ("  백업 완료: {0}" -f $bk)
Write-Host ("  zip  {0:N0}B · 백업 항목 {1}개" -f $zipInfo.Length, $count)
