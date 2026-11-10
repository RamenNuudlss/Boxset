# Sign Windows programs with the certificate in the SIGN_PFX (base64 .pfx) and
# SIGN_PASSWORD environment variables. Used by the build workflow when those
# repository secrets exist.
#   packaging/sign.ps1 dist/Boxset/Boxset.exe, dist/Boxset/boxset-cli.exe
param([Parameter(Mandatory = $true)][string[]]$Files)
$ErrorActionPreference = "Stop"

if (-not $env:SIGN_PFX) { throw "SIGN_PFX isn't set." }
$pfx = Join-Path $env:RUNNER_TEMP "boxset-sign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGN_PFX))
try {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
        Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe wasn't found on this machine." }
    foreach ($file in $Files) {
        & $signtool.FullName sign /f $pfx /p $env:SIGN_PASSWORD /fd SHA256 `
            /tr http://timestamp.digicert.com /td SHA256 /d "Boxset" $file
        if ($LASTEXITCODE -ne 0) { throw "Signing $file failed." }
    }
}
finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
