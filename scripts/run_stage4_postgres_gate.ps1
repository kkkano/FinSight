# ==========================================
# FinSight Stage4 Postgres gate local script
# One command: start pgvector -> run gate -> optional cleanup
# ==========================================

[CmdletBinding()]
param(
    [string]$ContainerName = "finsight-pgvector-local",
    [string]$Image = "pgvector/pgvector:pg16",
    [string]$PgHost = "127.0.0.1",
    [int]$PgPort = 5432,
    [string]$PostgresUser = "postgres",
    [string]$PostgresPassword = "postgres",
    [string]$PostgresDb = "postgres",
    [int]$WaitTimeoutSeconds = 120,
    [string]$PythonExe = "python",
    [string]$ReportPrefix = "local_pg",
    [string]$OutputDir = "tests/retrieval_eval/reports/local-postgres",
    [switch]$DriftGate,
    [switch]$NoDockerStart,
    [switch]$KeepDb
)

$ErrorActionPreference = "Stop"

function Assert-CommandExists {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Wait-ContainerHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $Name 2>$null
        if ($health -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Container health check timed out: $Name (>${TimeoutSeconds}s)"
}

$dsn = "postgresql+psycopg://{0}:{1}@{2}:{3}/{4}" -f $PostgresUser, $PostgresPassword, $PgHost, $PgPort, $PostgresDb
$cleanupContainer = $false

try {
    Assert-CommandExists -Name $PythonExe

    if (-not $NoDockerStart) {
        Assert-CommandExists -Name "docker"

        Write-Host "[1/4] Starting pgvector container: $ContainerName"
        docker rm -f $ContainerName *> $null
        docker run -d `
            --name $ContainerName `
            -e POSTGRES_USER=$PostgresUser `
            -e POSTGRES_PASSWORD=$PostgresPassword `
            -e POSTGRES_DB=$PostgresDb `
            -p "${PgPort}:5432" `
            --health-cmd "pg_isready -U $PostgresUser -d $PostgresDb" `
            --health-interval 5s `
            --health-timeout 3s `
            --health-retries 20 `
            $Image *> $null

        Write-Host "[2/4] Waiting for container health..."
        Wait-ContainerHealthy -Name $ContainerName -TimeoutSeconds $WaitTimeoutSeconds

        if (-not $KeepDb) {
            $cleanupContainer = $true
        }
    }
    else {
        Write-Host "[1/4] Skipping Docker start; using external Postgres"
    }

    Write-Host "[3/4] Running Stage4 Postgres retrieval gate"
    $env:RAG_EMBEDDING = "bge-m3"
    $env:RAG_V2_VECTOR_DIM = "1024"
    $env:RAG_V2_POSTGRES_DSN = $dsn

    $args = @(
        "tests/retrieval_eval/run_retrieval_eval.py",
        "--backend", "postgres",
        "--postgres-dsn", $dsn,
        "--gate",
        "--report-prefix", $ReportPrefix,
        "--output-dir", $OutputDir
    )

    if ($DriftGate) {
        $args += "--drift-gate"
    }

    & $PythonExe $args
    if ($LASTEXITCODE -ne 0) {
        throw "Retrieval gate failed with exit code: $LASTEXITCODE"
    }

    $gateSummaryPath = Join-Path -Path $OutputDir -ChildPath "gate_summary.json"
    Write-Host "[4/4] Done"
    Write-Host "Gate Summary: $gateSummaryPath"
}
finally {
    if ($cleanupContainer) {
        Write-Host "Cleaning container: $ContainerName"
        docker rm -f $ContainerName *> $null
    }
}

