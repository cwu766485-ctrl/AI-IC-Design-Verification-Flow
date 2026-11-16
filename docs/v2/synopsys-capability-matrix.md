# Synopsys Host Capability Matrix

**Audit date:** 2026-11-16
**Scope:** current local host inventory; not NM6008 project validation.

Status dimensions are independent:

- **Installed:** executable was discoverable by the environment checker.
- **Version:** executable reported a version; `TIMEOUT` means the probe did not complete, not that the tool is absent.
- **Licensed:** an actual feature checkout or an authorized successful invocation established availability.
- **Configured:** project-specific inputs and an adapter/configuration are available.
- **Tested:** stage execution evidence exists. “Generic fixture” does not mean NM6008.

| Tool / stage | Installed | Version evidence | License | NM6008 configured | NM6008 tested | Flow status / notes |
|---|---|---|---|---|---|---|
| VCS — compile/sim/regression | Yes | V-2023.12-SP1 | UNKNOWN for NM6008; generic fixture execution recorded elsewhere | No | No | Adapter exists; target is blocked on project inputs. |
| URG — coverage merge/report | Yes | V-2023.12-SP1 | UNKNOWN for NM6008; generic fixture evidence only | No | No | Adapter exists; coverage semantics require project reports/testplan. |
| Design Compiler — synthesis | Yes | V-2023.12-SP1 | UNKNOWN for NM6008; generic fixture evidence only | No | No | Adapter exists; no target library/SDC mapping. |
| Verdi — debug | Yes | Probe timed out; install tree indicates V-2023.12-SP2, not runtime-confirmed | UNKNOWN | No | No | Installed, runtime version and project debug setup unverified. |
| TestMAX DFT — scan insertion | Yes | Probe timed out; install tree indicates V-2023.12-SP5, not runtime-confirmed | UNKNOWN | No | No | Planned/unverified adapter; no DFT setup or scan-aware target netlist. |
| TestMAX ATPG | Yes | V-2023.12-SP5 | UNKNOWN | No | No | Planned/unverified adapter; requires scan netlist, libraries, test protocol and ATPG setup. |
| IC Compiler II — physical implementation | Yes | Version probe timed out; install tree indicates V-2023.12-SP3 | UNKNOWN | No | No | Planned/unverified; no NM6008 tech/physical setup. |
| PrimeTime — STA | Yes | V-2023.12-SP2 | UNKNOWN for NM6008; generic fixture evidence recorded elsewhere | No | No | Existing limited adapter; target MMMC/SDC/library profile missing. |
| Formality | Yes | V-2023.12-SP3 | UNKNOWN | No | No | Adapter/target equivalence setup not validated for NM6008. |
| SpyGlass | Yes | Probe unconfirmed; install tree indicates V-2023.12-SP1 | UNKNOWN | No | No | Lint/CDC signoff capability not established. |
| VC Formal | Yes | Probe unconfirmed; install tree indicates V-2023.12-SP2 | UNKNOWN | No | No | Formal adapter/feature availability not established. |
| StarRC | Yes | V-2023.12-SP2 | UNKNOWN | No | No | Planned/unverified; extraction tech files and run setup missing. |
| PrimePower | Separate executable not detected | UNKNOWN | UNKNOWN | No | No | Availability as a PrimeTime-integrated feature is also unverified. |
| IC Validator / ICV | No executable detected | — | UNKNOWN | No | No | Physical DRC/LVS stage unavailable on this host unless separately provisioned. |
| Fusion Compiler | No executable detected | — | UNKNOWN | No | No | Optional future Synopsys backend; excluded from initial implementation. |

## Interpretation

The environment checker was run without active license feature probes. This is intentional because project/license feature names and an authorized target flow were not supplied. Existing generic VCS/URG/DC/PrimeTime fixture evidence is documented in `docs/milestone1.md` and is not evidence for NM6008, its libraries, TestMAX, ICC2, extraction, physical verification, or signoff.

The checker did not test an SSH runner. No remote host is included in the capability claim. Before remote execution, require an explicitly authorized host, matching-clean-checkout preflight, and evidence copied back through the existing remote runner.

## Gate before marking a tool usable

For each stage, record all four independent facts in the run manifest: executable/version fingerprint, license checkout result, validated project configuration and input hashes, and tested stage result. Any unknown required fact blocks that stage; installed-only tools stay `BLOCKED` or `NOT_RUN`, never `PASS`.
