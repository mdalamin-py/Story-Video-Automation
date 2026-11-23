param(
    [ValidateSet('Check','Voice','Render','Captions')][string]$Action = 'Check',
    [string]$Project,
    [string]$Video,
    [string]$Out,
    [string]$Size = '640x360',
    [string]$Voice = 'bn-BD-NabanitaNeural'
)
$ErrorActionPreference = 'Stop'
$Runtime = 'C:\Users\HP\Documents\Codex\2026-11-22\d-video-maker-cinematic-skill'
$Python = Join-Path $Runtime 'work\cinematic-venv\Scripts\python.exe'
$LocalPython = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '.venv\Scripts\python.exe'
if (Test-Path $LocalPython) { $Python = $LocalPython }
$env:PATH = "$(Join-Path $Runtime 'work\win32');$env:PATH"
$env:PYTHONUTF8 = '1'
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$env:CINEMATIC_REPO = $Repo
$Helper = Join-Path $PSScriptRoot 'bangla_tools.py'
if ($Action -eq 'Check') {
    & $Python -X utf8 "$Repo\skills\cinematic-film\scripts\check_setup.py"
    if ($LASTEXITCODE -ne 0) { throw 'Setup check failed' }
    & $Python -c 'import edge_tts; print("Online voice helper available (any Edge TTS language)")'
} else {
    if (!$Project) { throw '-Project is required' }
    if ($Action -eq 'Voice') {
        & $Python -X utf8 $Helper voice --project $Project --voice $Voice
    } elseif ($Action -eq 'Render') {
        if (!$Out) { $Out = Join-Path $Project 'out\draft.mp4' }
        & $Python -X utf8 (Join-Path $PSScriptRoot 'render_serial.py') --project $Project --size $Size --out $Out --audio audio\narration.m4a
    } elseif ($Action -eq 'Captions') {
        if (!$Video) { $Video = Join-Path $Project 'out\draft.mp4' }
        if (!$Out) { $Out = Join-Path $Project 'out\final-video.mp4' }
        & $Python -X utf8 $Helper captions --project $Project --video $Video --out $Out
    }
}
if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
