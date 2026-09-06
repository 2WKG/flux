# Pester 5 suite for deploy/tunnel.ps1's preflight (2WKG-274).
#
# Run by `gate/deploy-preflight` in .github/workflows/pr-gates.yml, so a change to
# tunnel.ps1 is checked rather than merely parsed. Two things this file is careful
# about, because the first cut of it got both wrong:
#
#  1. Scope. `& $script` runs the script in a child scope, and Pester 5 injects its
#     mocks into the *test* scope, so a mock defined here does reach the script --
#     but only for commands the script resolves by name at call time. The suite
#     asserts that by counting the mocked calls (`Should -Invoke`), so a mock that
#     silently failed to apply is a red test, not a green one.
#  2. Distinguishability. A mock that answers the same for the static origin and
#     the API cannot tell the two states apart, which is the whole point of the
#     preflight. Every mock below branches on the URI and the assertions pin which
#     branch produced which line of output.

# A non-2xx response is an *exception* in Windows PowerShell/pwsh, and tunnel.ps1
# reads the status back off it (`$_.Exception.Response.StatusCode.value__`). These
# two types reproduce that exact shape so the 503-accepted and 500-refused branches
# exercise the code an operator actually hits, rather than a shape invented here.
# `[System.Net.HttpStatusCode]` is a real enum, so `.value__` resolves the way it
# does against a live `HttpResponseException`.
class MockHttpResponse {
    [System.Net.HttpStatusCode]$StatusCode
}

class MockHttpException : System.Exception {
    [MockHttpResponse]$Response
    MockHttpException([int]$code) : base("HTTP $code") {
        $this.Response = [MockHttpResponse]@{ StatusCode = [System.Net.HttpStatusCode]$code }
    }
}

BeforeAll {
    $global:FluxScriptUnderTest = Join-Path $PSScriptRoot '..' 'tunnel.ps1' | Resolve-Path | Select-Object -ExpandProperty Path
    # tunnel.ps1 is a Windows operator script and `gate/deploy-preflight` runs it on
    # windows-latest, where USERPROFILE is always set. Supplying it when absent lets
    # the same suite run on a developer's macOS/Linux box without changing behaviour
    # on Windows: the credentials directory is probed only through mocked
    # Test-Path/Get-ChildItem either way.
    if (-not $env:USERPROFILE) { $env:USERPROFILE = [System.IO.Path]::GetTempPath() }
    $global:FluxStaticUri = 'http://127.0.0.1:4173/'
    $global:FluxApiUri = 'http://127.0.0.1:8000/health'

}

Describe 'tunnel.ps1 preflight' {
    BeforeEach {
        Mock Get-Command { [pscustomobject]@{ Source = 'mock-cloudflared' } }
        Mock Test-Path { $true }
        Mock Get-ChildItem { @([pscustomobject]@{ Name = 'mock.json' }) }
        $global:FluxPreflightSaid = [System.Collections.Generic.List[string]]::new()
        Mock Write-Host { $global:FluxPreflightSaid.Add([string]$Object) }
        # The connector must never start during a preflight test.
        function global:cloudflared { throw 'cloudflared must not run during preflight tests' }
    }

    AfterEach {
        Remove-Item Function:\global:cloudflared -ErrorAction SilentlyContinue
    }

    It 'passes when the API health endpoint answers 200, and says so about the API specifically' {
        Mock Invoke-WebRequest {
            if ($Uri -eq $global:FluxStaticUri) { return [pscustomobject]@{ StatusCode = 200 } }
            if ($Uri -eq $global:FluxApiUri) { return [pscustomobject]@{ StatusCode = 200 } }
            throw "unexpected preflight URI: $Uri"
        }

        { & $global:FluxScriptUnderTest -CheckOnly } | Should -Not -Throw

        # Both origins were actually probed through the mock (proves the mock applied).
        Should -Invoke Invoke-WebRequest -Times 1 -Exactly -ParameterFilter { $Uri -eq $global:FluxStaticUri }
        Should -Invoke Invoke-WebRequest -Times 1 -Exactly -ParameterFilter { $Uri -eq $global:FluxApiUri }
        # And the green line names the API's own endpoint and status, not the static origin's.
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'ok\s+API health: http://127\.0\.0\.1:8000/health returned 200'
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'ok\s+origin: http://127\.0\.0\.1:4173/ returned 200'
    }

    It 'does not pass on the static origin alone when the API is the thing that is down' {
        # The mock that made the original suite a tautology returned 200 for both
        # branches. This one returns 200 only for the static origin, so a preflight
        # that never looked at the API would wrongly pass here.
        Mock Invoke-WebRequest {
            if ($Uri -eq $global:FluxStaticUri) { return [pscustomobject]@{ StatusCode = 200 } }
            throw [MockHttpException]::new(500)
        }

        { & $global:FluxScriptUnderTest -CheckOnly } | Should -Throw -ExpectedMessage '*preflight check(s) failed; the tunnel was not started.*'
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'FAIL The API health endpoint is not answering'
        ($global:FluxPreflightSaid -join "`n") | Should -Not -Match 'ok\s+API health'
    }

    It 'accepts the documented unavailable 503 from the API' {
        Mock Invoke-WebRequest {
            if ($Uri -eq $global:FluxStaticUri) { return [pscustomobject]@{ StatusCode = 200 } }
            throw [MockHttpException]::new(503)
        }

        { & $global:FluxScriptUnderTest -CheckOnly } | Should -Not -Throw
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'documented unavailable 503'
    }

    It 'fails closed before the connector when API health cannot connect at all' {
        Mock Invoke-WebRequest {
            if ($Uri -eq $global:FluxStaticUri) { return [pscustomobject]@{ StatusCode = 200 } }
            throw 'connection refused'
        }

        { & $global:FluxScriptUnderTest } | Should -Throw -ExpectedMessage '*preflight check(s) failed; the tunnel was not started.*'
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'FAIL The API health endpoint is not answering'
    }

    It 'fails closed when the static origin is down, and names the static origin' {
        Mock Invoke-WebRequest {
            if ($Uri -eq $global:FluxStaticUri) { throw 'connection refused' }
            return [pscustomobject]@{ StatusCode = 200 }
        }

        { & $global:FluxScriptUnderTest } | Should -Throw -ExpectedMessage '*preflight check(s) failed; the tunnel was not started.*'
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'FAIL The static origin is not answering'
        ($global:FluxPreflightSaid -join "`n") | Should -Match 'ok\s+API health'
    }
}
