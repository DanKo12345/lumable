param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,

    [Parameter(Mandatory = $true)]
    [string]$IcoPath
)

$signature = @'
using System;
using System.Runtime.InteropServices;

public static class NativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr BeginUpdateResource(string pFileName, bool bDeleteExistingResources);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool UpdateResource(
        IntPtr hUpdate,
        IntPtr lpType,
        IntPtr lpName,
        ushort wLanguage,
        byte[] lpData,
        uint cbData);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool EndUpdateResource(IntPtr hUpdate, bool fDiscard);
}
'@

if (-not ([System.Management.Automation.PSTypeName]'NativeMethods').Type) {
    Add-Type -TypeDefinition $signature
}

function Read-UInt16LE {
    param([byte[]]$Bytes, [int]$Offset)
    [BitConverter]::ToUInt16($Bytes, $Offset)
}

function Read-UInt32LE {
    param([byte[]]$Bytes, [int]$Offset)
    [BitConverter]::ToUInt32($Bytes, $Offset)
}

$ico = [IO.File]::ReadAllBytes($IcoPath)
$count = Read-UInt16LE $ico 4

if ($count -lt 1) {
    throw "ICO file does not contain any images."
}

$entries = @()
for ($i = 0; $i -lt $count; $i++) {
    $entryOffset = 6 + ($i * 16)
    $width = $ico[$entryOffset]
    $height = $ico[$entryOffset + 1]
    $colorCount = $ico[$entryOffset + 2]
    $reserved = $ico[$entryOffset + 3]
    $planes = Read-UInt16LE $ico ($entryOffset + 4)
    $bitCount = Read-UInt16LE $ico ($entryOffset + 6)
    $bytesInRes = Read-UInt32LE $ico ($entryOffset + 8)
    $imageOffset = Read-UInt32LE $ico ($entryOffset + 12)
    $imageData = New-Object byte[] $bytesInRes
    [Array]::Copy($ico, [int]$imageOffset, $imageData, 0, [int]$bytesInRes)

    $entries += [pscustomobject]@{
        Width      = $width
        Height     = $height
        ColorCount = $colorCount
        Reserved   = $reserved
        Planes     = $planes
        BitCount   = $bitCount
        BytesInRes = $bytesInRes
        ResourceId = [UInt16]($i + 1)
        Data       = $imageData
    }
}

$groupStream = New-Object IO.MemoryStream
$groupWriter = New-Object IO.BinaryWriter($groupStream)

try {
    $groupWriter.Write([UInt16]0)
    $groupWriter.Write([UInt16]1)
    $groupWriter.Write([UInt16]$entries.Count)

    foreach ($entry in $entries) {
        $groupWriter.Write([byte]$entry.Width)
        $groupWriter.Write([byte]$entry.Height)
        $groupWriter.Write([byte]$entry.ColorCount)
        $groupWriter.Write([byte]$entry.Reserved)
        $groupWriter.Write([UInt16]$entry.Planes)
        $groupWriter.Write([UInt16]$entry.BitCount)
        $groupWriter.Write([UInt32]$entry.BytesInRes)
        $groupWriter.Write([UInt16]$entry.ResourceId)
    }

    $groupData = $groupStream.ToArray()
}
finally {
    $groupWriter.Dispose()
    $groupStream.Dispose()
}

$RT_ICON = [IntPtr]3
$RT_GROUP_ICON = [IntPtr]14
$LANG_NEUTRAL = [UInt16]0
$GROUP_ID = [IntPtr]1

$handle = [NativeMethods]::BeginUpdateResource($ExePath, $false)
if ($handle -eq [IntPtr]::Zero) {
    throw "BeginUpdateResource failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}

$ok = $true

foreach ($entry in $entries) {
    $namePtr = [IntPtr][int]$entry.ResourceId
    if (-not [NativeMethods]::UpdateResource($handle, $RT_ICON, $namePtr, $LANG_NEUTRAL, $entry.Data, [uint32]$entry.Data.Length)) {
        $ok = $false
        break
    }
}

if ($ok) {
    $ok = [NativeMethods]::UpdateResource($handle, $RT_GROUP_ICON, $GROUP_ID, $LANG_NEUTRAL, $groupData, [uint32]$groupData.Length)
}

if (-not [NativeMethods]::EndUpdateResource($handle, (-not $ok))) {
    throw "EndUpdateResource failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}

if (-not $ok) {
    throw "UpdateResource failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
