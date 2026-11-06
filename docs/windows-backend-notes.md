# Windows backend implementation notes

The backend uses only Python standard-library Win32 calls, loaded lazily. Non-Windows imports work, but native operations refuse to run there. Native Windows CI is required before recording a Windows result; macOS path-policy results do not substitute for it. All fixtures are synthetic. Real sleep and user-LAN/client acceptance remain separate, deferred checks.

## Files and workspace

Only explicit local drive-absolute paths are admitted. UNC, device namespaces, alternate data streams, traversal, DOS device names, wildcard/control characters, trailing dots/spaces and ambiguous path components are refused. The native backend requires a local fixed volume with persistent ACL support and rejects reparse points including volume-mount reparses. Network and removable volumes are unsupported.

`CreateFileW` opens every ancestor with `FILE_FLAG_OPEN_REPARSE_POINT`, checks its directory attributes and volume serial, and holds the handles until the final file is open. Ancestor handles deny write/delete sharing during traversal. The final handle must report an ordinary disk file with no reparse attribute. Sources have read-only access and share only reading, so concurrent ordinary writers or deletion attempts fail. `msvcrt.open_osfhandle` transfers ownership to an ordinary Python descriptor; callers must close it with `os.close`. Core retains its descriptor identity/size/timestamp comparisons and source re-open checks.

Private runtime reads deliberately allow read/write/delete sharing, supporting atomic heartbeat replacement and expiry deletion even with open read descriptors. They still reject reparses/nonfiles and check the final file's owner and DACL. Missing private records preserve `FileNotFoundError`, allowing absent optional control/probe records to be treated as absent. ACL, reparse and sharing failures remain explicit security errors; missing sources remain `source_invalid`.

A workspace is created atomically using a protected security descriptor containing the actual process `TokenUser` SID as owner and its only full-control allow ACE, with object/container inheritance. `create_private` and `make_private_dir` create every runtime file/directory with an explicit `TokenUser` owner and a protected user-only DACL from creation. Parent directories also carry object/container inheritance, but file ownership does not depend on token default-owner or owner inheritance. QR files are securely pre-created before the renderer writes them; `chmod` is never treated as Windows confidentiality. Existing directories are never re-ACL'd or adopted without a valid `.lan-share-root` version-1 marker. Validation rejects NULL/empty DACLs, non-user owners, additional principals, unknown ACE types and ineffective/non-inheritable directory grants. This intentionally refuses some otherwise safe custom ACLs. Explicit per-object ownership also handles elevated process tokens whose default owner is Administrators, without altering process-token defaults or accepting a group owner. Both creation APIs require a validated private parent, retain ancestor handles through native exclusive creation, and refuse all existing objects. OS administrators, backup privileges and other processes running as the same user remain outside this per-user isolation boundary.

## Runtime and networking

`GetTickCount64` provides system-uptime milliseconds, with no ordinary monotonic fallback. Suspend-inclusive behavior is based on the native clock contract, not a performed sleep test. Background processes use `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`. A fixed, read-only PowerShell script queries only up physical adapters and preferred IPv4 addresses; Python independently filters exact RFC1918 ranges. Its output is UTF-8 and execution is bounded to ten seconds. No adapters, firewall, routes or permissions are changed.

## Primary references

- [CreateFileW sharing modes and reparse flags](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Naming files, paths and namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
- [GetFileInformationByHandle identity fields](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [GetSecurityInfo ownership, DACL and buffer lifetime](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
- [ACE inheritance rules](https://learn.microsoft.com/en-us/windows/win32/secauthz/ace-inheritance-rules)
- [Owner of a new object and token default owner](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)
- [Volume persistent-ACL capability](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationw)
- [GetTickCount64](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-gettickcount64)
- [Get-NetAdapter physical adapter selection](https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapter?view=windowsserver2025-ps)
