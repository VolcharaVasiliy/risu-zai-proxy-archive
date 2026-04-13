param()

$root = 'C:\Users\gamer\AppData\Roaming\chat2api\Partitions'

if (-not (Test-Path -LiteralPath $root)) {
  throw "Chat2API partitions folder not found: $root"
}

$partitions = Get-ChildItem -LiteralPath $root -Directory |
  Where-Object { $_.Name -like 'oauth-*' } |
  Sort-Object LastWriteTime -Descending

if (-not $partitions) {
  throw "No oauth-* partition found in $root"
}

foreach ($partition in $partitions) {
  $levelDb = Join-Path $partition.FullName 'Local Storage\leveldb'
  if (-not (Test-Path -LiteralPath $levelDb)) {
    continue
  }

  $logFiles = Get-ChildItem -LiteralPath $levelDb -Filter '*.log' -File | Sort-Object LastWriteTime -Descending
  foreach ($logFile in $logFiles) {
    $content = Get-Content -LiteralPath $logFile.FullName -Raw
    if (-not $content) {
      continue
    }
    if ($content -notmatch 'chat\.z\.ai') {
      continue
    }

    $matches = [regex]::Matches($content, 'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+') | ForEach-Object Value
    if ($matches.Count -gt 0) {
      $matches[-1].Trim()
      return
    }
  }
}

throw "No Z.ai JWT token found under $root"
