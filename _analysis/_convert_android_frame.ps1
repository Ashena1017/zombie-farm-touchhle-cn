param([string]$Dir = '_analysis\dumps\android-frame-probe')
Add-Type -AssemblyName System.Drawing
$taskFrameDir = (Resolve-Path -LiteralPath $Dir).Path
foreach ($file in Get-ChildItem -LiteralPath $taskFrameDir -Filter '*.rgba') {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    for ($i=0; $i -lt $bytes.Length; $i+=4) {
        $red=$bytes[$i]; $bytes[$i]=$bytes[$i+2]; $bytes[$i+2]=$red
    }
    $bitmap=New-Object Drawing.Bitmap(320,480,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $data=$bitmap.LockBits([Drawing.Rectangle]::new(0,0,320,480),[Drawing.Imaging.ImageLockMode]::WriteOnly,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
    [Runtime.InteropServices.Marshal]::Copy($bytes,0,$data.Scan0,$bytes.Length)
    $bitmap.UnlockBits($data)
    $bitmap.RotateFlip([Drawing.RotateFlipType]::RotateNoneFlipY)
    $bitmap.RotateFlip([Drawing.RotateFlipType]::Rotate270FlipNone)
    $bitmap.Save([IO.Path]::ChangeExtension($file.FullName,'.png'),[Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
}
