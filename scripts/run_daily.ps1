# Runs the daily report pipeline locally (Windows Task Scheduler calls this,
# see test.md "로컬 PC 스케줄링"). Only succeeds if this machine has network
# access to mail.hoban.co.kr at run time (company WiFi/VPN) — that's the
# whole reason this moved off GitHub Actions.

$ErrorActionPreference = "Continue"
$RepoDir = "C:\Users\tec\Desktop\vscode\AI_report"
$PythonExe = "C:\Users\tec\AppData\Local\Python\pythoncore-3.14-64\python.exe"

Set-Location $RepoDir

$LogDir = Join-Path $RepoDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Start-Transcript -Path (Join-Path $LogDir "daily_$(Get-Date -Format 'yyyy-MM-dd').log") -Append

git pull --quiet

& $PythonExe main.py --now
$exitCode = $LASTEXITCODE

git add data/
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git -c user.name="local-scheduler" -c user.email="hannau416@gmail.com" commit -m "chore: data $(Get-Date -Format 'yyyy-MM-dd')"
    git push
}

Stop-Transcript
exit $exitCode
