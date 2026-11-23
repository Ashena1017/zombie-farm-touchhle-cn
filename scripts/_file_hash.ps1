# Use .NET so Windows PowerShell 5.1 can hash files even when launched from pwsh.
function Get-Sha256Hex {
    [CmdletBinding(DefaultParameterSetName = 'Path')]
    param(
        [Parameter(Mandatory = $true, Position = 0, ParameterSetName = 'Path')][string]$Path,
        [Parameter(Mandatory = $true, ParameterSetName = 'Stream')][IO.Stream]$Stream
    )

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        if ($PSCmdlet.ParameterSetName -eq 'Stream') {
            return ([BitConverter]::ToString($sha.ComputeHash($Stream))).Replace('-', '')
        }
        $file = [IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($file))).Replace('-', '')
        } finally {
            $file.Dispose()
        }
    } finally {
        $sha.Dispose()
    }
}
