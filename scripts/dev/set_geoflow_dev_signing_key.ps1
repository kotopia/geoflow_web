function Set-GeoFlowDevSigningKey {
    param([Parameter(Mandatory = $true)][string]$Scope)
    if ($env:OS -ne 'Windows_NT' -or $env:GEOFLOW_DEV_RUNTIME_STRICT -ne '1') {
        throw 'Persistent development signing keys require Windows and strict development mode.'
    }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
    $digest = [Security.Cryptography.SHA256]::Create()
    try { $scopeId = ([BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($Scope)))).Replace('-', '').ToLowerInvariant() }
    finally { $digest.Dispose() }
    $directory = Join-Path $env:LOCALAPPDATA 'GeoFlow\dev-runtime'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $keyFile = Join-Path $directory ($scopeId + '.dpapi')
    if (-not [IO.File]::Exists($keyFile)) {
        $bytes = New-Object byte[] 48
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $secure = ConvertTo-SecureString ([Convert]::ToBase64String($bytes)) -AsPlainText -Force
        # Windows DPAPI encrypts for the current Windows user; never commit a key.
        $encrypted = ConvertFrom-SecureString $secure
        $temporary = Join-Path $directory ([Guid]::NewGuid().ToString() + '.tmp')
        try {
            [IO.File]::WriteAllText($temporary, $encrypted)
            try { [IO.File]::Move($temporary, $keyFile) }
            catch { if (-not [IO.File]::Exists($keyFile)) { throw } }
        } finally {
            if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
            [Array]::Clear($bytes, 0, $bytes.Length)
        }
    }
    # Invalid/unreadable keys fail closed rather than silently rotating sessions.
    $secure = ConvertTo-SecureString ([IO.File]::ReadAllText($keyFile))
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        if ([string]::IsNullOrWhiteSpace($value)) { throw 'Development signing key is empty.' }
        $env:DJANGO_SECRET_KEY = $value
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        $value = $null
    }
    Write-Host 'Development signing key loaded from Windows-protected local storage.'
}
