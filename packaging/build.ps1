# Builds the portable zip: packaging\out\HeadTracker-portable-<version>.zip
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$py = Join-Path $root '.venv\Scripts\python.exe'
$ver = (Select-String -Path (Join-Path $root 'app\ui.py') -Pattern '^VERSION = "([^"]+)"').Matches[0].Groups[1].Value
$work = Join-Path $here 'build'
$dist = Join-Path $here 'dist'
$out = Join-Path $here 'out'

& $py -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist (Join-Path $here 'HeadTracker.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
$app = Join-Path $dist 'Head Tracker'

# Visual C++ runtime next to the program, so a fresh Windows without the redistributable works too
$internal = Join-Path $app '_internal'
foreach ($dll in 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll') {
    $have = Get-ChildItem $app -Recurse -Filter $dll -ErrorAction SilentlyContinue | Select-Object -First 1
    $sys = Join-Path $env:WINDIR "System32\$dll"
    if (-not $have -and (Test-Path $sys)) { Copy-Item -LiteralPath $sys -Destination $internal; "added $dll" }
}
Copy-Item -LiteralPath (Join-Path $here 'README.txt') -Destination $app

New-Item -ItemType Directory -Force $out | Out-Null
$zip = Join-Path $out "HeadTracker-portable-$ver.zip"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
"built $zip ($size MB)"
