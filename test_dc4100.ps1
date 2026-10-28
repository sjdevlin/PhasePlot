param(
    [string]$Port = "COM8",
    [ValidateRange(1, 4)][int]$Channel,
    [ValidateRange(0, 100)][double]$Brightness,
    [ValidateRange(0.01, 60)][double]$PulseSeconds
)

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found at $python"
}

$arguments = @("-m", "utilities.test_dc4100", "--port", $Port)
if ($PSBoundParameters.ContainsKey("Channel") -or
    $PSBoundParameters.ContainsKey("Brightness") -or
    $PSBoundParameters.ContainsKey("PulseSeconds")) {
    if (-not ($PSBoundParameters.ContainsKey("Channel") -and
              $PSBoundParameters.ContainsKey("Brightness") -and
              $PSBoundParameters.ContainsKey("PulseSeconds"))) {
        throw "Channel, Brightness, and PulseSeconds must all be supplied for an LED pulse."
    }
    $arguments += @(
        "--channel", $Channel,
        "--brightness", $Brightness,
        "--pulse-seconds", $PulseSeconds
    )
}

& $python @arguments
exit $LASTEXITCODE
