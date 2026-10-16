<#
Journey Forever - cloud sync (docs/Sharing_Design.md, version 2). Uses only what Windows brings along.

The shared cloud folder holds only player data (<cloud>\players). The addon and this script come from a local
clone of the git repository: after a git pull, the next run installs the new version.

  Setup (sync\Einrichten.bat in the repository clone):
      powershell -ExecutionPolicy Bypass -File ForeverSync.ps1 -Setup
  Background (started hidden at Windows login by ForeverSync.vbs from the Startup folder):
      powershell -ExecutionPolicy Bypass -File ForeverSync.ps1 -Loop
  One run (tests, troubleshooting):
      powershell -ExecutionPolicy Bypass -File ForeverSync.ps1 -Once

Each run:
  1. updates this script from <repo>\sync
  2. installs a newer addon from <repo>\addons (only while WoW is not running; keeps Friends\FriendsData.lua)
  3. uploads this PC's ForeverChronicle_Share.lua (per WoW account) to <cloud>\players\<name>-<id>-<account hash>.lua
     (name: the one friends see; id: the first 8 characters of the shareId); renamed when the name changes
  4. downloads all other players' files, accepts only pure data, writes ForeverChronicle_Share\Friends\FriendsData.lua
  5. daily backup of the addon's SavedVariables (newest 10 days kept)
Settings and log: %LOCALAPPDATA%\ForeverChronicle\sync (config.json, sync.log, state.json).
#>
[CmdletBinding()]
param(
  [switch]$Setup,
  [switch]$Loop,
  [switch]$Once,
  [string]$CloudFolder,     # setup: the shared folder (default: the last one, else found in OneDrive, else asked)
  [string]$RepoFolder,      # setup: the repository clone (default: the parent of the folder this script is in)
  [string]$ClientFolder,    # setup: the WoW Forever client folder (default: found automatically)
  [string]$DataDir,         # where settings, log and backups live (default: %LOCALAPPDATA%\ForeverChronicle\sync)
  [switch]$NoStartup,       # setup: do not add the Startup entry (tests)
  [int]$IntervalMinutes = 10
)

$ErrorActionPreference = 'Stop'
$ScriptVersion = 2
$CloudName = 'Journey Forever Cloud'
$AddonNames = @('ForeverChronicle', 'ForeverChronicle_Share')
$ShareFile = 'ForeverChronicle_Share.lua'
$FriendsFile = 'FriendsData.lua'
$MaxFriendBytes = 8MB
$MaxTotalBytes = 60MB
$ForeverFlavors = @('wow_classic_beta')
# Player files: <name>-<id>-<account>.lua, or <shareId>-<account>.lua from scripts before 2026-10-16.
$PlayerFileName = [regex]::new(
  '^(?:(?<name>[\p{L}\p{N}_]{1,24})-(?<id>[0-9a-f]{8})|(?<id>[0-9a-f]{32}))-(?<account>[0-9a-f]{8})\.lua$')

if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA 'ForeverChronicle\sync' }
$ConfigPath = Join-Path $DataDir 'config.json'
$StatePath = Join-Path $DataDir 'state.json'
$LogPath = Join-Path $DataDir 'sync.log'

# -- helpers ----------------------------------------------------------------------------------------

function Write-Log([string]$Message) {
  New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
  if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) {
    Move-Item -Force $LogPath "$LogPath.old"
  }
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  Write-Verbose $line
}

function Read-Json([string]$Path) {
  if (-not (Test-Path $Path)) { return $null }
  try { return Get-Content -Raw -Path $Path -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Write-Json([string]$Path, $Value) {
  New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
  $Value | ConvertTo-Json -Depth 6 | Set-Content -Path $Path -Encoding UTF8
}

function Write-FileAtomic([string]$Path, [byte[]]$Bytes) {
  New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
  $tmp = "$Path.tmp"
  [IO.File]::WriteAllBytes($tmp, $Bytes)
  Move-Item -Force -Path $tmp -Destination $Path
}

function Get-Sha([byte[]]$Bytes) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLower() } finally { $sha.Dispose() }
}

function Get-TocVersion([string]$AddonFolder) {
  $toc = Join-Path $AddonFolder ((Split-Path $AddonFolder -Leaf) + '.toc')
  if (-not (Test-Path $toc)) { return $null }
  foreach ($line in Get-Content -Path $toc -Encoding UTF8) {
    if ($line -match '^## Version:\s*([0-9][0-9.]*)') {
      try { return [Version]$matches[1] } catch { return $null }
    }
  }
  return $null
}

# -- finding the game ---------------------------------------------------------------------------------

function Get-Flavor([string]$Folder) {
  $info = Join-Path $Folder '.flavor.info'
  if (-not (Test-Path $info)) { return $null }
  $lines = @(Get-Content -Path $info -ErrorAction SilentlyContinue)
  if ($lines.Count -gt 1) { return $lines[1].Trim() }
  return $null
}

function Find-ClientIn([string]$Root) {
  if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
  if ($ForeverFlavors -contains (Get-Flavor $Root)) { return $Root }
  foreach ($child in Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue) {
    if ($ForeverFlavors -contains (Get-Flavor $child.FullName)) { return $child.FullName }
  }
  return $null
}

# Install folders Battle.net knows: product.db (paths as plain strings), Battle.net.config, uninstall entries.
function Get-BattleNetRoots {
  $roots = @()
  $db = Join-Path $env:ProgramData 'Battle.net\Agent\product.db'
  if (Test-Path $db) {
    $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($db))
    foreach ($m in [regex]::Matches($text, '[A-Za-z]:/[^\x00-\x1f"]{2,200}')) { $roots += $m.Value }
  }
  $cfg = Join-Path $env:APPDATA 'Battle.net\Battle.net.config'
  if (Test-Path $cfg) {
    try {
      $default = (Get-Content -Raw $cfg | ConvertFrom-Json).Client.Install.DefaultInstallPath
      if ($default) { $roots += (Join-Path $default 'World of Warcraft') }
    } catch { }
  }
  foreach ($key in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
                   'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                   'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*') {
    foreach ($entry in Get-ItemProperty $key -ErrorAction SilentlyContinue) {
      if ($entry.DisplayName -like '*World of Warcraft*' -and $entry.InstallLocation) { $roots += $entry.InstallLocation }
    }
  }
  return $roots
}

function Find-Client {
  foreach ($root in Get-BattleNetRoots) {
    # product.db strings may run into the next field: try the path and its shorter prefixes ending in a folder.
    $candidate = $root -replace '/', '\'
    while ($candidate.Length -gt 3) {
      $found = Find-ClientIn $candidate
      if ($found) { return $found }
      $cut = $candidate.LastIndexOf('\')
      if ($cut -lt 3) { break }
      $candidate = $candidate.Substring(0, $cut)
    }
  }
  foreach ($drive in Get-PSDrive -PSProvider FileSystem) {
    foreach ($sub in 'Program Files (x86)', 'Program Files', 'Games', '') {
      $found = Find-ClientIn (Join-Path (Join-Path $drive.Root $sub) 'World of Warcraft')
      if ($found) { return $found }
    }
  }
  return $null
}

function Test-GameRunning([string]$Client) {
  foreach ($p in Get-Process -ErrorAction SilentlyContinue) {
    try { if ($p.Path -and $p.Path.StartsWith($Client, [StringComparison]::OrdinalIgnoreCase)) { return $true } } catch { }
  }
  return $false
}

# -- pure data check ------------------------------------------------------------------------------------

# A friend's file must be exactly "ForeverChronicleShareDB = <table>" with nothing but data in the table:
# strings, numbers, true/false/nil, braces, brackets, '=', ',' and comments - no names, no calls, no long strings.
# One linear match (atomic groups: no backtracking), fast also for files of several MB.
$PureData = [regex]::new(
  '\A\s*ForeverChronicleShareDB\s*=\s*\{(?>(?>\s+|--[^\r\n]*|"(?>[^"\\\r\n]|\\[\s\S])*"|-?(?>\d+\.?\d*|\.\d+)(?>[eE][+-]?\d+)?|true\b|false\b|nil\b|[{}\]=,;]|\[(?![\[=]))*)\z',
  [Text.RegularExpressions.RegexOptions]::Compiled)

function Test-PureData([string]$Text) {
  return $PureData.IsMatch($Text)
}

# -- steps --------------------------------------------------------------------------------------------

function Update-Self($Config) {
  if (-not $Config.repo) { return }  # set up before version 2: run sync\Einrichten.bat from the repository
  $src = Join-Path $Config.repo 'sync'
  foreach ($name in 'ForeverSync.ps1', 'ForeverSync.vbs') {
    $from = Join-Path $src $name
    $to = Join-Path $DataDir $name
    if ((Test-Path $from) -and (-not (Test-Path $to) -or (Get-FileHash $from).Hash -ne (Get-FileHash $to).Hash)) {
      Copy-Item -Force $from $to
      Write-Log "updated $name"
      if ($name -eq 'ForeverSync.ps1') { $script:Restart = $true }
    }
  }
}

function Update-Addon($Config) {
  if (-not $Config.repo) { return }
  $addons = Join-Path $Config.client 'Interface\AddOns'
  $source = Join-Path $Config.repo 'addons'
  $newest = Get-TocVersion (Join-Path $source 'ForeverChronicle')
  if (-not $newest) { return }
  $installed = Get-TocVersion (Join-Path $addons 'ForeverChronicle')
  $shareMissing = -not (Test-Path (Join-Path $addons 'ForeverChronicle_Share'))
  if ($installed -and $newest -le $installed -and -not $shareMissing) { return }
  if (Test-GameRunning $Config.client) { Write-Log "addon $newest waits: WoW is running"; return }
  foreach ($name in $AddonNames) {
    $from = Join-Path $source $name
    if (Test-Path $from) {
      New-Item -ItemType Directory -Force -Path $addons | Out-Null
      robocopy $from (Join-Path $addons $name) /MIR /XF $FriendsFile /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $name ($LASTEXITCODE)" }
    }
  }
  $friends = Join-Path $addons "ForeverChronicle_Share\Friends\$FriendsFile"
  if (-not (Test-Path $friends)) { $script:ForceFriends = $true }
  Write-Log "addon installed: $installed -> $newest"
}

function Get-ShareFiles($Config) {
  $accounts = Join-Path $Config.client 'WTF\Account'
  if (-not (Test-Path $accounts)) { return @() }
  return @(Get-ChildItem -Path $accounts -Directory | ForEach-Object {
    $file = Join-Path $_.FullName "SavedVariables\$ShareFile"
    if (Test-Path $file) { [pscustomobject]@{ Account = $_.Name; Path = $file } }
  })
}

# The name friends see (the top-level "name" of a share file), reduced to letters and digits for a file name.
function Get-PlayerName([string]$Text) {
  $name = ''
  if ($Text -match '(?m)^[ \t]?\["name"\]\s*=\s*"((?:[^"\\\r\n]|\\.)*)"') { $name = $matches[1] }
  $name = (($name -replace '\\.', '') -replace '[^\p{L}\p{N}]+', '_').Trim('_')
  if ($name.Length -gt 24) { $name = $name.Substring(0, 24).TrimEnd('_') }
  if (-not $name) { $name = 'Spieler' }
  return $name
}

function Test-OwnFile($Config, [string]$Name) {
  $m = $PlayerFileName.Match($Name)
  return $m.Success -and $Config.shareId.StartsWith($m.Groups['id'].Value)
}

function Send-Own($Config, $State) {
  $players = Join-Path $Config.cloud 'players'
  foreach ($f in Get-ShareFiles $Config) {
    $bytes = [IO.File]::ReadAllBytes($f.Path)
    $text = [Text.Encoding]::UTF8.GetString($bytes)
    $hash = Get-Sha $bytes
    $accountId = (Get-Sha ([Text.Encoding]::UTF8.GetBytes($f.Account))).Substring(0, 8)
    $target = Join-Path $players ('{0}-{1}-{2}.lua' -f (Get-PlayerName $text), $Config.shareId.Substring(0, 8), $accountId)
    $key = "upload:$accountId"
    if ($State.$key -eq $hash -and (Test-Path $target)) { continue }
    if (-not (Test-PureData $text)) { Write-Log "own share file is not plain data, skipped: $($f.Path)"; continue }
    Write-FileAtomic $target $bytes
    $State | Add-Member -Force -NotePropertyName $key -NotePropertyValue $hash
    Write-Log ("uploaded {0} ({1:N0} KB)" -f (Split-Path $target -Leaf), ($bytes.Length / 1KB))
    # The same account under an older name (renamed in game, or the naming before 2026-10-16): removed.
    foreach ($old in Get-ChildItem -Path $players -Filter "*-$accountId.lua" -File) {
      if ($old.FullName -ne $target -and (Test-OwnFile $Config $old.Name)) {
        Remove-Item -Force $old.FullName
        Write-Log "removed old upload $($old.Name)"
      }
    }
  }
}

function Get-LongBracketLevel([string]$Text) {
  $level = 1
  while ($Text.Contains(']' + ('=' * $level) + ']')) { $level++ }
  return $level
}

function Receive-Friends($Config, $State) {
  $players = Join-Path $Config.cloud 'players'
  $target = Join-Path $Config.client "Interface\AddOns\ForeverChronicle_Share\Friends\$FriendsFile"
  if (-not (Test-Path (Split-Path $target))) { return }  # addon not installed (yet)
  $accepted = @()
  $total = 0
  if (Test-Path $players) {
    foreach ($file in Get-ChildItem -Path $players -Filter '*.lua' -File | Sort-Object Name) {
      if (-not $PlayerFileName.IsMatch($file.Name)) { Write-Log "ignored unexpected file $($file.Name)"; continue }
      if (Test-OwnFile $Config $file.Name) { continue }
      if ($file.Length -gt $MaxFriendBytes -or $total + $file.Length -gt $MaxTotalBytes) {
        Write-Log "skipped $($file.Name): too large"; continue
      }
      try { $text = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8) } catch { Write-Log "unreadable $($file.Name)"; continue }
      if (-not (Test-PureData $text)) { Write-Log "rejected $($file.Name): not plain data"; continue }
      $accepted += [pscustomobject]@{ Name = $file.Name; Text = $text }
      $total += $file.Length
    }
  }
  $sb = New-Object Text.StringBuilder
  [void]$sb.AppendLine('-- Journey Forever: friends'' characters, written by the sync script (ForeverSync.ps1). Do not edit.')
  [void]$sb.AppendLine('ForeverChronicleFriends = { version = 2, friends = {}, maps = {}, instances = {}, entrances = {} }')
  [void]$sb.AppendLine('local F, setfenv, loadstring, load, pcall, type, pairs = ForeverChronicleFriends, setfenv, loadstring, load, pcall, type, pairs')
  [void]$sb.AppendLine(@'
-- Each friend's file is checked as plain data by the sync script and still runs alone, in an empty sandbox.
local function add(source, text)
  local env = {}
  local fn = loadstring and loadstring(text, source) or load(text, source, "t", env)
  if not fn then return end
  if setfenv then setfenv(fn, env) end
  if not pcall(fn) then return end
  local d = env.ForeverChronicleShareDB
  if type(d) ~= "table" or type(d.characters) ~= "table" then return end
  F.friends[#F.friends + 1] = { name = type(d.name) == "string" and d.name or "?", characters = d.characters,
    addonVersion = d.addonVersion, generatedAt = d.generatedAt, source = source }
  for _, part in pairs({ "maps", "instances", "entrances" }) do
    if type(d[part]) == "table" then
      for k, v in pairs(d[part]) do if F[part][k] == nil then F[part][k] = v end end
    end
  end
end
'@)
  foreach ($friend in $accepted) {
    $level = '=' * (Get-LongBracketLevel $friend.Text)
    [void]$sb.Append('add("').Append($friend.Name).Append('", [').Append($level).Append("[`n")
    [void]$sb.Append($friend.Text).Append("`n]").Append($level).AppendLine('])')
  }
  $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($sb.ToString())
  $hash = Get-Sha $bytes
  if ($State.friends -eq $hash -and (Test-Path $target) -and -not $script:ForceFriends) { return }
  Write-FileAtomic $target $bytes
  $State | Add-Member -Force -NotePropertyName 'friends' -NotePropertyValue $hash
  Write-Log ("friends file written: {0} friend file(s), visible in game after /reload" -f $accepted.Count)
}

function Backup-SavedVariables($Config, $State) {
  $today = Get-Date -Format 'yyyy-MM-dd'
  if ($State.backup -eq $today) { return }
  $accounts = Join-Path $Config.client 'WTF\Account'
  if (-not (Test-Path $accounts)) { return }
  $dest = Join-Path $DataDir "backups\$today"
  $count = 0
  foreach ($file in Get-ChildItem -Path $accounts -Recurse -File -Filter 'ForeverChronicle*.lua' -ErrorAction SilentlyContinue) {
    if ($file.DirectoryName -notlike '*\SavedVariables') { continue }
    $account = Split-Path (Split-Path $file.DirectoryName) -Leaf
    $to = Join-Path $dest $account
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Copy-Item -Force $file.FullName $to
    $count++
  }
  $all = @(Get-ChildItem -Path (Join-Path $DataDir 'backups') -Directory -ErrorAction SilentlyContinue | Sort-Object Name)
  if ($all.Count -gt 10) { $all[0..($all.Count - 11)] | Remove-Item -Recurse -Force }
  $State | Add-Member -Force -NotePropertyName 'backup' -NotePropertyValue $today
  if ($count) { Write-Log "backup: $count file(s) to $dest" }
}

function Invoke-Sync {
  $config = Read-Json $ConfigPath
  if (-not $config -or -not $config.cloud -or -not $config.client) { Write-Log 'not set up (run Einrichten.bat)'; return }
  if (-not (Test-Path $config.cloud)) { Write-Log "cloud folder not available: $($config.cloud)"; return }
  $state = Read-Json $StatePath
  if (-not $state) { $state = [pscustomobject]@{} }
  $script:ForceFriends = $false
  foreach ($step in 'Update-Self', 'Update-Addon', 'Send-Own', 'Receive-Friends', 'Backup-SavedVariables') {
    try {
      if ($step -eq 'Update-Self' -or $step -eq 'Update-Addon') { & $step $config } else { & $step $config $state }
    } catch {
      Write-Log "$step failed: $($_.Exception.Message)"
    }
  }
  Write-Json $StatePath $state
}

# -- setup ----------------------------------------------------------------------------------------------

function Test-Repo([string]$Folder) {
  return $Folder -and (Test-Path (Join-Path $Folder 'addons\ForeverChronicle\ForeverChronicle.toc')) -and
         (Test-Path (Join-Path $Folder 'sync\ForeverSync.ps1'))
}

# The shared folder in this PC's OneDrive (also as a shortcut to a folder someone else shared).
function Find-Cloud {
  foreach ($root in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) | Where-Object { $_ } | Select-Object -Unique) {
    foreach ($candidate in (Join-Path $root $CloudName), (Join-Path $root "Shortcuts\$CloudName")) {
      if (Test-Path (Join-Path $candidate 'players')) { return $candidate }
    }
  }
  return $null
}

function Invoke-Setup {
  $old = Read-Json $ConfigPath
  if (-not $RepoFolder) { $RepoFolder = Split-Path (Split-Path $PSCommandPath) }
  if (-not (Test-Repo $RepoFolder) -and $old -and (Test-Repo $old.repo)) { $RepoFolder = $old.repo }
  if (-not (Test-Repo $RepoFolder)) { throw "Kein Journey-Forever-Repository: $RepoFolder (sync\Einrichten.bat im Repository starten)" }
  $RepoFolder = (Resolve-Path $RepoFolder).Path
  if (-not $CloudFolder -and $old -and $old.cloud -and (Test-Path (Join-Path $old.cloud 'players'))) { $CloudFolder = $old.cloud }
  if (-not $CloudFolder) { $CloudFolder = Find-Cloud }
  if (-not $CloudFolder) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Gemeinsamen Cloud-Ordner waehlen ($CloudName)"
    if ($dialog.ShowDialog() -eq 'OK') { $CloudFolder = $dialog.SelectedPath }
  }
  if (-not $CloudFolder -or -not (Test-Path $CloudFolder -PathType Container)) { throw 'Kein Cloud-Ordner gewaehlt.' }
  New-Item -ItemType Directory -Force -Path (Join-Path $CloudFolder 'players') | Out-Null
  if (-not $ClientFolder) { $ClientFolder = Find-Client }
  if (-not $ClientFolder) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'WoW-Forever-Ordner waehlen (World of Warcraft oder _classic_beta_)'
    if ($dialog.ShowDialog() -eq 'OK') { $ClientFolder = Find-ClientIn $dialog.SelectedPath }
  }
  if (-not $ClientFolder) { throw 'WoW Forever wurde nicht gefunden.' }
  $shareId = if ($old -and $old.shareId -match '^[0-9a-f]{32}$') { $old.shareId } else { [guid]::NewGuid().ToString('N') }
  New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
  Write-Json $ConfigPath ([pscustomobject]@{ cloud = $CloudFolder; repo = $RepoFolder; client = $ClientFolder;
                                             shareId = $shareId; interval = $IntervalMinutes; scriptVersion = $ScriptVersion })
  foreach ($name in 'ForeverSync.ps1', 'ForeverSync.vbs') {
    Copy-Item -Force (Join-Path (Join-Path $RepoFolder 'sync') $name) (Join-Path $DataDir $name)
  }
  if (-not $NoStartup) {
    # A loop of an older version would keep running until the next login: stop it, the new one starts below.
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*ForeverSync.ps1*-Loop*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $startup = [Environment]::GetFolderPath('Startup')
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $startup 'Journey Forever Sync.lnk'))
    $link.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $link.Arguments = '"' + (Join-Path $DataDir 'ForeverSync.vbs') + '"'
    $link.Description = 'Journey Forever: Addon und Freunde-Daten mit dem Cloud-Ordner abgleichen'
    $link.Save()
  }
  Write-Log "setup: cloud $CloudFolder, repo $RepoFolder, client $ClientFolder"
  Invoke-Sync
  if (-not $NoStartup) { Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wscript.exe') -ArgumentList ('"' + (Join-Path $DataDir 'ForeverSync.vbs') + '"') }
  Write-Host ''
  Write-Host 'Journey Forever Sync ist eingerichtet.'
  Write-Host "  Cloud-Ordner: $CloudFolder (nur Spielerdaten)"
  Write-Host "  Repository:   $RepoFolder (Addon-Updates: nach git pull automatisch)"
  Write-Host "  Spiel:        $ClientFolder"
  Write-Host '  Laeuft ab jetzt unsichtbar bei jeder Windows-Anmeldung (alle 10 Minuten).'
  Write-Host '  Im Spiel nach einem Update oder neuen Freunde-Daten: /reload'
}

# -- main -------------------------------------------------------------------------------------------------

if ($Setup) { Invoke-Setup; return }
if ($Once) { Invoke-Sync; return }
if ($Loop) {
  $mutex = New-Object Threading.Mutex($false, 'Local\ForeverChronicleSync')
  if (-not $mutex.WaitOne(0)) { return }   # already running
  try {
    Write-Log "sync started (script version $ScriptVersion)"
    while ($true) {
      $script:Restart = $false
      Invoke-Sync
      if ($script:Restart) {
        Write-Log 'restarting with the updated script'
        $mutex.ReleaseMutex()
        Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wscript.exe') -ArgumentList ('"' + (Join-Path $DataDir 'ForeverSync.vbs') + '"')
        return
      }
      $config = Read-Json $ConfigPath
      $minutes = if ($config -and $config.interval) { [int]$config.interval } else { $IntervalMinutes }
      Start-Sleep -Seconds ([Math]::Max(1, $minutes) * 60)
    }
  } finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
  }
}
