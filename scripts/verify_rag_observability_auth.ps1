param(
  [string]$BaseUrl = 'http://127.0.0.1:8000',
  [Parameter(Mandatory = $true)]
  [string]$AccessToken,
  [string]$InternalApiKey = '',
  [string]$RunId = 'run-1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-CurlCheck {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string[]]$CurlArgs,
    [Parameter(Mandatory = $true)]
    [int[]]$ExpectedCodes
  )

  $bodyFile = [System.IO.Path]::GetTempFileName()
  try {
    $httpCode = & curl.exe -sS -o $bodyFile -w '%{http_code}' @CurlArgs
    if ($LASTEXITCODE -ne 0) {
      throw "curl failed for ${Name}"
    }

    $code = [int]::Parse(($httpCode | Out-String).Trim())
    $body = Get-Content $bodyFile -Raw

    Write-Host "[${Name}] HTTP ${code}" -ForegroundColor Cyan
    if ($body) {
      Write-Host $body
    }

    if ($ExpectedCodes -notcontains $code) {
      throw "${Name} expected HTTP $($ExpectedCodes -join ',') but got ${code}"
    }

    return [pscustomobject]@{
      Name = $Name
      StatusCode = $code
      Body = $body
    }
  }
  finally {
    Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
  }
}

function New-CurlJsonBodyFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Json
  )

  $path = [System.IO.Path]::GetTempFileName()
  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($path, $Json, $encoding)
  return $path
}

$normalizedBaseUrl = $BaseUrl.TrimEnd('/')
$readerMutationBodyFile = New-CurlJsonBodyFile -Json '{"deleted_by":"reader-script","reason":"auth-boundary-check"}'
$internalMutationBodyFile = New-CurlJsonBodyFile -Json '{"deleted_by":"ops-script","reason":"auth-boundary-check"}'

try {
  Write-Host '== RAG observability auth verification ==' -ForegroundColor Green
  Write-Host "Base URL: ${normalizedBaseUrl}"

  Invoke-CurlCheck -Name 'anonymous-read' -ExpectedCodes @(401) -CurlArgs @(
    '--request', 'GET',
    "${normalizedBaseUrl}/diagnostics/rag/status"
  ) | Out-Null

  Invoke-CurlCheck -Name 'bearer-read' -ExpectedCodes @(200) -CurlArgs @(
    '--request', 'GET',
    '--header', "Authorization: Bearer ${AccessToken}",
    "${normalizedBaseUrl}/diagnostics/rag/status"
  ) | Out-Null

  Invoke-CurlCheck -Name 'bearer-mutation-denied' -ExpectedCodes @(403) -CurlArgs @(
    '--request', 'POST',
    '--header', 'Content-Type: application/json',
    '--header', "Authorization: Bearer ${AccessToken}",
    '--data-binary', "@${readerMutationBodyFile}",
    "${normalizedBaseUrl}/diagnostics/rag/runs/${RunId}/soft-delete"
  ) | Out-Null

  if ([string]::IsNullOrWhiteSpace($InternalApiKey)) {
    Write-Host '[internal-mutation] skipped (no InternalApiKey provided)' -ForegroundColor Yellow
  } else {
    Invoke-CurlCheck -Name 'internal-mutation' -ExpectedCodes @(200, 404) -CurlArgs @(
      '--request', 'POST',
      '--header', 'Content-Type: application/json',
      '--header', "x-api-key: ${InternalApiKey}",
      '--data-binary', "@${internalMutationBodyFile}",
      "${normalizedBaseUrl}/diagnostics/rag/runs/${RunId}/soft-delete"
    ) | Out-Null
  }

  Write-Host 'RAG observability auth verification passed.' -ForegroundColor Green
}
finally {
  Remove-Item $readerMutationBodyFile -Force -ErrorAction SilentlyContinue
  Remove-Item $internalMutationBodyFile -Force -ErrorAction SilentlyContinue
}
