$scriptUnderTest = Join-Path $PSScriptRoot '..\tunnel.ps1'

Describe 'tunnel preflight API health' {
  BeforeEach {
    Mock Get-Command { [pscustomobject]@{ Source = 'mock-cloudflared' } }
    Mock Test-Path { $true }
    Mock Get-ChildItem { @([pscustomobject]@{ Name = 'mock.json' }) }
    Mock Write-Host {}
    function global:cloudflared { throw 'cloudflared must not run during preflight tests' }
  }

  AfterEach {
    Remove-Item Function:\global:cloudflared -ErrorAction SilentlyContinue
  }

  It 'accepts an API health 200 during CheckOnly' {
    Mock Invoke-WebRequest {
      param($Uri)
      [pscustomobject]@{ StatusCode = if ($Uri -match ':4173/') { 200 } else { 200 } }
    }

    { & $scriptUnderTest -CheckOnly } | Should Not Throw
  }

  It 'accepts the documented API health 503 during CheckOnly' {
    Mock Invoke-WebRequest {
      param($Uri)
      [pscustomobject]@{ StatusCode = if ($Uri -match ':4173/') { 200 } else { 503 } }
    }

    { & $scriptUnderTest -CheckOnly } | Should Not Throw
  }

  It 'fails closed before the connector for API 500' {
    Mock Invoke-WebRequest {
      param($Uri)
      [pscustomobject]@{ StatusCode = if ($Uri -match ':4173/') { 200 } else { 500 } }
    }

    $failure = $null
    try { & $scriptUnderTest } catch { $failure = $_ }
    $failure | Should Not Be $null
    $failure.Exception.Message | Should Match 'preflight check\(s\) failed; the tunnel was not started'
  }

  It 'fails closed before the connector when API health cannot connect' {
    Mock Invoke-WebRequest {
      param($Uri)
      if ($Uri -match ':4173/') { return [pscustomobject]@{ StatusCode = 200 } }
      throw 'connection refused'
    }

    $failure = $null
    try { & $scriptUnderTest } catch { $failure = $_ }
    $failure | Should Not Be $null
    $failure.Exception.Message | Should Match 'preflight check\(s\) failed; the tunnel was not started'
  }
}
