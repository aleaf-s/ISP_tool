param(
    [string]$PythonExe = "python"
)

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $projectRoot
try {
    & $PythonExe "tools\native_backend_doctor.py"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonExe "native\setup_native.py" build_ext --inplace --force
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonExe "tools\native_backend_doctor.py" --verify --benchmark
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
