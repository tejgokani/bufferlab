# One-line installer (Windows PowerShell):
#   irm https://raw.githubusercontent.com/tejgokani/bufferlab/main/install.ps1 | iex
# Clones BufferLab to %USERPROFILE%\bufferlab, adds a `bufferlab` shim directory to your *user* PATH, and
# builds the environment inside the clone. The command re-checks Python and the environment on every run.
$ErrorActionPreference = 'Stop'
$repo = if ($env:BUFFERLAB_REPO) { $env:BUFFERLAB_REPO } else { 'https://github.com/tejgokani/bufferlab.git' }
$dest = if ($env:BUFFERLAB_DIR) { $env:BUFFERLAB_DIR } else { Join-Path $HOME 'bufferlab' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git is required: winget install Git.Git' }
if (Test-Path (Join-Path $dest '.git')) { git -C $dest pull --ff-only }
elseif (Test-Path $dest) { throw "$dest exists and is not a BufferLab clone; set BUFFERLAB_DIR." }
else { git clone --depth 1 $repo $dest }
$shim = Join-Path $HOME '.bufferlab\bin'
New-Item -ItemType Directory -Force $shim | Out-Null
Set-Content -Path (Join-Path $shim 'bufferlab.cmd') -Value "@echo off`r`n`"$dest\bin\bufferlab.cmd`" %*"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $shim) {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$shim", 'User')
  Write-Host "Added $shim to your user PATH (open a new terminal to use 'bufferlab')."
}
& (Join-Path $dest 'bin\bufferlab.cmd') --version
Write-Host 'Done. Start it with:  bufferlab'
