$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv (Join-Path $PSScriptRoot '.build-venv')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create build environment' }
}
& $buildPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed' }
$bundledLicenses = Join-Path $PSScriptRoot 'build\release-licenses\BUNDLED_LICENSES.txt'
& $buildPython (Join-Path $PSScriptRoot 'tools\collect_licenses.py') $bundledLicenses
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
& $buildPython -m PyInstaller --noconfirm (Join-Path $PSScriptRoot 'TokenDuck.spec')
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
$releaseVersion = [regex]::Match((Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tokenduck.py') -Raw -Encoding utf8), '(?m)^APP_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"').Groups[1].Value
if (-not $releaseVersion) { throw 'Cannot read application version' }
$releaseExe = Join-Path $PSScriptRoot 'dist\TokenDuck.exe'
$releaseFolder = Join-Path $PSScriptRoot ('dist\TokenDuck-' + $releaseVersion + '-windows')
New-Item -ItemType Directory -Path $releaseFolder -Force | Out-Null
Copy-Item -LiteralPath $releaseExe -Destination $releaseFolder -Force
foreach ($name in @('README.md', 'README.en.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $releaseFolder -Force
}
foreach ($name in @('docs', 'assets', 'licenses')) {
    New-Item -ItemType Directory -Path (Join-Path $releaseFolder $name) -Force | Out-Null
}
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'docs') -Filter '*.md' | Copy-Item -Destination (Join-Path $releaseFolder 'docs') -Force
foreach ($name in @('tokenduck.svg', 'preview.svg')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('assets\' + $name)) -Destination (Join-Path $releaseFolder 'assets') -Force
}
Copy-Item -LiteralPath $bundledLicenses -Destination (Join-Path $releaseFolder 'licenses') -Force
$exeDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseExe).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $releaseFolder 'SHA256SUMS.txt') -Value ($exeDigest + '  TokenDuck.exe') -Encoding ascii
$releaseZip = $releaseFolder + '.zip'
$releaseFiles = @(Get-ChildItem -LiteralPath $releaseFolder | Select-Object -ExpandProperty FullName)
Compress-Archive -LiteralPath $releaseFiles -DestinationPath $releaseZip -Force
$zipDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseZip).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dist\SHA256SUMS.txt') -Value @(
    ($exeDigest + '  TokenDuck.exe'),
    ($zipDigest + '  ' + (Split-Path -Leaf $releaseZip))
) -Encoding ascii
Write-Output ('Ready: ' + $releaseZip)
