param(
    [Parameter(Mandatory = $true)]
    [string]$GameRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputIco
)

$pngs = @(
    (Join-Path $GameRoot 'UI\ic_16x16.png'),
    (Join-Path $GameRoot 'UI\ic_32x32.png'),
    (Join-Path $GameRoot 'UI\ic_128x128.png'),
    (Join-Path $GameRoot 'UI\ic_256x256.png')
) | Where-Object { Test-Path -LiteralPath $_ }

if ($pngs.Count -eq 0) {
    throw "Не найдены исходные PNG-иконки в папке UI."
}

$images = foreach ($path in $pngs) {
    $name = [IO.Path]::GetFileNameWithoutExtension($path)
    if ($name -match '(\d+)x(\d+)') {
        $width = [int]$matches[1]
        $height = [int]$matches[2]
    }
    else {
        throw "Не удалось определить размер иконки: $path"
    }

    [pscustomobject]@{
        Path   = $path
        Width  = $width
        Height = $height
        Bytes  = [IO.File]::ReadAllBytes($path)
    }
}

$dir = Split-Path -Parent $OutputIco
if ($dir) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$stream = [IO.File]::Open($OutputIco, [IO.FileMode]::Create, [IO.FileAccess]::Write)
$writer = New-Object IO.BinaryWriter($stream)

try {
    $writer.Write([UInt16]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]$images.Count)

    $offset = 6 + (16 * $images.Count)

    foreach ($image in $images) {
        $widthByte = if ($image.Width -ge 256) { 0 } else { [byte]$image.Width }
        $heightByte = if ($image.Height -ge 256) { 0 } else { [byte]$image.Height }

        $writer.Write($widthByte)
        $writer.Write($heightByte)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([UInt16]1)
        $writer.Write([UInt16]32)
        $writer.Write([UInt32]$image.Bytes.Length)
        $writer.Write([UInt32]$offset)

        $offset += $image.Bytes.Length
    }

    foreach ($image in $images) {
        $writer.Write($image.Bytes)
    }
}
finally {
    $writer.Dispose()
    $stream.Dispose()
}
