# Stores the shared QA test account in secrets/accounts.json (git-ignored).
# The file is read only by the local engine at login time; it never reaches the API or reports.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$secretsDir = Join-Path $projectRoot 'secrets'
$secretsFile = Join-Path $secretsDir 'accounts.json'
Write-Host '공용 테스트 계정을 이 PC의 secrets/accounts.json 에 저장합니다 (git 제외, 서버·보고서 미전송).'
$accountId = Read-Host '테스트 계정 ID'
if (-not $accountId) { throw 'ID is required.' }
$secure = Read-Host '비밀번호 (입력 중 표시되지 않음)' -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure))
if (-not $plain) { throw 'Password is required.' }
if (-not (Test-Path -LiteralPath $secretsDir)) { New-Item -ItemType Directory -Path $secretsDir | Out-Null }
$payload = @{ accounts = @{ default = @{ id = $accountId; pw = $plain } } } | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText($secretsFile, $payload, (New-Object Text.UTF8Encoding $false))
$plain = $null
Write-Host "저장 완료: $secretsFile"
Write-Host '모든 환경(A/B)과 계정 키 default 에 이 계정이 쓰입니다. 환경별로 다른 계정이 필요하면 파일에 default.a / default.b 항목을 추가하세요.'
