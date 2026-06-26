# Executive Incident Report: Suspicious Execution Chain Involving WINWORD.EXE and PowerShell

## Executive Summary

An endpoint detection and response (EDR) alert identified suspicious activity involving the spawning of powershell.exe by WINWORD.EXE with an encoded command, followed by rundll32.exe executing a suspicious DLL entrypoint. Additionally, a scheduled task was created, likely for persistence, and network connections to an unfamiliar external IP address were observed, indicating potential command and control (C2) communication. The attack techniques map to known adversary behaviors involving PowerShell execution, system binary proxy execution, scheduled tasks for persistence, and web protocols for C2. Immediate containment and remediation actions are recommended to prevent further compromise and to investigate the scope of the intrusion.

## Likely Attack Flow

- WINWORD.EXE spawns powershell.exe with an encoded command, indicating initial command execution.
- Powershell executes malicious or encoded payloads to further the attack.
- Rundll32.exe is used to execute a suspicious DLL entrypoint, leveraging system binary proxy execution for defense evasion.
- A scheduled task is created to maintain persistence on the compromised system.
- Network connections are established to an unfamiliar external IP, suggesting command and control communication.
- Potential data exfiltration or further remote commands may be issued via web protocols.

## Mapped Techniques

- T1059.001 PowerShell (Execution)
- T1218 System Binary Proxy Execution (Defense Evasion)
- T1053.005 Scheduled Task (Execution, Persistence, Privilege Escalation)
- T1071.001 Web Protocols (Command And Control)

## Notable Groups and Software Associated

- PowerShell (T1059.001): Groups - WIRTE, APT42, APT5, Blue Mockingbird, APT39; Software - Empire, Covenant, Pupy, Koadic, Sliver
- System Binary Proxy Execution (T1218): Groups - Lazarus Group, Volt Typhoon
- Scheduled Task (T1053.005): Groups - APT3, Cobalt Group, Silence, Chimera, Patchwork; Software - CSPY Downloader, IronNetInjector, PowerSploit, MCMD, Empire
- Web Protocols (T1071.001): Groups - Rancor, Metador, RedEcho, BITTER, Moonstone Sleet; Software - PoshC2, PcShare, Out1, Mythic, Quick Assist

## Detection Recommendations

- Monitor for encoded PowerShell commands and unusual spawning of powershell.exe by office applications like WINWORD.EXE.
- Alert on rundll32.exe executing DLLs from non-standard locations or with suspicious entrypoints.
- Detect creation and modification of scheduled tasks, especially those created outside of normal administrative processes.
- Monitor outbound network connections to unfamiliar or suspicious external IP addresses, particularly over web protocols.
- Implement behavioral analytics to identify proxy execution of system binaries.
- Correlate process creation events with network activity to detect potential C2 communications.
- Leverage endpoint detection tools to flag execution prevention bypass attempts.
- Audit privileged account usage and scheduled task creation for anomalies.

## Immediate Actions

- Isolate affected endpoints to prevent lateral movement and further external communication.
- Collect and preserve forensic evidence including process execution logs, scheduled task configurations, and network traffic captures.
- Perform a full malware scan and remove any identified malicious payloads or scheduled tasks.
- Block identified suspicious external IP addresses at the network perimeter and firewall.
- Review and restrict PowerShell execution policies and monitor for encoded command usage.
- Audit and restrict use of system binaries like rundll32.exe to trusted processes only.
- Review scheduled tasks across endpoints for unauthorized persistence mechanisms.
- Notify relevant internal teams and stakeholders of the incident and ongoing investigation.

## Indicators of Compromise (IOCs)

### Suspected Artifacts

- Encoded PowerShell command spawned by WINWORD.EXE
- Suspicious DLL loaded by rundll32.exe
- Scheduled task created for persistence

### Suspicious Processes

- WINWORD.EXE spawning powershell.exe
- powershell.exe with encoded commands
- rundll32.exe executing suspicious DLL

### Suspicious Network

- Outbound connections to unfamiliar external IP addresses

