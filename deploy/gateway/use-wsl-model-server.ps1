# Points this PowerShell session's gateway (machine A, Windows) at:
#   - primary:  the mock company provider (python -m mock_provider.service) on 127.0.0.1
#   - fallback: the WSL model server (machine B) behind its TLS + token proxy
#
# Run from the repo root, dot-sourced so the variables stay in this session:
#   . .\deploy\gateway\use-wsl-model-server.ps1
#
# The proxy token is read straight from WSL into an environment variable; it is never printed or
# written to the repository. The proxy's CA certificate (public) is copied to %USERPROFILE%.
param(
    [string]$Distro = "Ubuntu",
    [string]$Model = "qwen2.5-coder:1.5b",
    [int]$CompanyProviderPort = 8900
)

$addrLine = (wsl -d $Distro -e ip -4 -o addr show eth0 | Out-String)
if ($addrLine -notmatch 'inet (\d+\.\d+\.\d+\.\d+)/') {
    throw "Could not read the WSL eth0 address from distro '$Distro'."
}
$wslIp = $Matches[1]

$token = (wsl -d $Distro -e sh -c 'cat "$HOME/.config/secure-llm-gateway/model-proxy-token" 2>/dev/null' | Out-String).Trim()
$caPem = wsl -d $Distro -e sh -c 'cat "$HOME/.local/share/caddy/pki/authorities/local/root.crt" 2>/dev/null'
if (-not $token -or -not $caPem) {
    throw "Proxy token or CA not found in WSL. Run 'bash deploy/model-server/start-proxy.sh' in WSL first."
}

$caDir = Join-Path $env:USERPROFILE ".secure-llm-gateway"
New-Item -ItemType Directory -Force -Path $caDir | Out-Null
$caPath = Join-Path $caDir "model-server-ca.crt"
$caPem | Set-Content -Path $caPath -Encoding ascii

$env:APP_PROFILE = "local"
$env:PRIMARY_PROVIDER = "openai_compat"
$env:FALLBACK_PROVIDER = "ollama"
$env:ALLOW_SIMULATION = "false"  # real errors only

# Mock company provider; it accepts any key. Use a real key only for an approved company account.
$env:OPENAI_COMPAT_BASE_URL = "http://127.0.0.1:$CompanyProviderPort/v1"
$env:OPENAI_COMPAT_MODEL = "company-model"
$env:OPENAI_COMPAT_API_KEY = "demo-company-key"

$env:OLLAMA_BASE_URL = "https://${wslIp}:8443"
$env:OLLAMA_MODEL = $Model
$env:OLLAMA_API_KEY = $token
$env:OLLAMA_CA_BUNDLE = $caPath
Remove-Item Env:OLLAMA_ALLOW_PLAINTEXT_TUNNEL -ErrorAction SilentlyContinue

Write-Host "Gateway configured for this session:"
Write-Host "  primary : openai_compat -> $($env:OPENAI_COMPAT_BASE_URL) (mock company provider)"
Write-Host "  fallback: ollama        -> $($env:OLLAMA_BASE_URL) (WSL model server, TLS + token)"
Write-Host "  model   : $Model"
Write-Host "  CA      : $caPath"
Write-Host "Try: python -m app.cli ask `"Explain exponential backoff in one sentence.`" --repeat 6"
