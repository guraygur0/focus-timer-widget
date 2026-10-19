param([string]$Python = "python", [switch]$NoDependencies)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$exe = (& $Python -c "import sys; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
if (!$NoDependencies) {
    & $exe -m pip install -r (Join-Path $project 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$pythonw = Join-Path (Split-Path $exe) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe not found.' }
$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$def = $svc.NewTask(0)
$def.RegistrationInfo.Description = 'Focus Timer Widget desktop widget'
$def.Principal.LogonType = 3
$def.Settings.Enabled = $true
$def.Settings.StartWhenAvailable = $true
$def.Settings.DisallowStartIfOnBatteries = $false
$def.Settings.StopIfGoingOnBatteries = $false
$def.Settings.ExecutionTimeLimit = 'PT0S'
$def.Settings.MultipleInstances = 2
$def.Settings.RestartCount = 10
$def.Settings.RestartInterval = 'PT1M'
$trigger = $def.Triggers.Create(9)
$trigger.UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger.Delay = 'PT20S'
$action = $def.Actions.Create(0)
$action.Path = $pythonw
$action.Arguments = '"' + (Join-Path $project 'launch.pyw') + '"'
$action.WorkingDirectory = $project
$task = $svc.GetFolder('\').RegisterTaskDefinition('GurOS Focus Timer', $def, 6, $trigger.UserId, $null, 3)
$task.Run($null) | Out-Null
Write-Output 'Focus Timer Widget installed and started. Right-click the widget for settings.'
