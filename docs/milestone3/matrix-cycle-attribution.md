# Matrix Cycle Attribution

The 2026-11-14 profile separates the Matrix core's Prefetch Wait state into
exclusive primary cycle classes and separates productive writes from output
backpressure. Its decision is **no RTL candidate yet**: the evidence shows
where baseline cycles occur but does not establish how much prefetch drain is
exposed on the critical path.

## Evidence

- NMAForge source: `4b62f8e815bb272ab9b727dff4736cec460e6f21`
- Flow adapter: `00be752330c4acb56bc019e42be95283edda80b7`
- VCS: `V-2023.12-SP1_Full64`; regression seeds `20261021/20261022/20261023`
- Performance seed: `20261113`; five workloads, 2010 total cycles,
  `46.10547 MAC/cycle`
- Stage Runtime regression, reference model, latency gate, and performance:
  all `PASS`; elapsed `14.430263 s`
- Runtime plan SHA-256:
  `2b436550bcf7cc99ff957ddd9a412b0337a736e47df85585db9277ca7376e0a5`
- Performance summary SHA-256:
  `5994d61ab3b8608d5d1b4dc6895b1d04981e6c2daee8fd0570b1fc183458411e`
- Performance command log SHA-256:
  `76610ed7e3d07c042142a95c6c3f1fdb5b6fa00168360119f3457ac72b48f85a`
- Matrix core SHA-256:
  `3eeb8809ba79dd4a375b7aa0d58a7ecca37591bb7405afc57d2ee94c1c94a38a`
- Testbench SHA-256:
  `dc161fbfd737ce84c8acd2887f3ac9e5d501664b075bc28946f39e1fb1120c7e`

The full reviewed profile and archived Stage Runtime files are in the NMAForge
feature branch at
`docs/verification/artifacts/MATRIX_CYCLE_ATTRIBUTION_2026-11-14/`; its report
is `docs/verification/MATRIX_CYCLE_ATTRIBUTION_2026-11-14.md`. This run is a
baseline-only campaign, not a comparison of Candidate 001R2 or Candidate
002R2, and is not ASIC PPA evidence.

## Results

| Workload MxNxK | Cycles | Prefetch wait | Denial | FIFO full | Request grant | Outstanding drain | Handoff ready | Write | Productive | Writeback stall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4x4x32 | 78 | 22 | 0 | 0 | 1 | 14 | 7 | 8 | 4 | 4 |
| 8x8x32 | 110 | 42 | 1 | 0 | 15 | 19 | 7 | 17 | 16 | 1 |
| 16x16x32 | 230 | 84 | 13 | 0 | 36 | 28 | 7 | 89 | 64 | 25 |
| 16x32x32 | 403 | 129 | 32 | 0 | 41 | 42 | 14 | 163 | 128 | 35 |
| 32x32x64 | 1189 | 500 | 77 | 0 | 183 | 180 | 60 | 320 | 256 | 64 |
| Total | 2010 | 777 | 123 | 0 | 276 | 283 | 95 | 597 | 468 | 129 |

The largest workload spends 42.05% of its cycles in Prefetch Wait. Denial is
15.4% of that state and FIFO-full is zero, so increasing outstanding depth is
not supported by this profile. Grant and outstanding-drain buckets describe
progress while the FSM is waiting; the data does not tell whether drain is
already hidden under MAC or exposed on the critical path. The 64 writeback
stall cycles align with 64 line denial events, indicating line-ready
backpressure at the interface. Event counters can overlap FSM states and must
not be added to the exclusive state partitions.

Across all five workloads, the aggregate arbiter-stall, banked-denial,
line-denial, and scalar-denial event counters are 362, 233, 129, and 0.
Within `32x32x64` they are 210, 146, 64, and 0. The 123 prefetch-wait denial
buckets are the primary classification only within that FSM state and are not
the same metric as global banked-request denials.

The next useful measurement is a cross-tab of `ST_PREFETCH_WAIT` against
`PF_A_REQ`, `PF_A_DRAIN`, `PF_B_REQ`, and `PF_B_DRAIN`, with denial and response
drain intersections, or a controlled ready/response-latency sweep. Until that
isolates exposed cycles, an A-to-B overlap change remains an untested
hypothesis and no RTL candidate is proposed. No RTL improvement or ASIC PPA
result is claimed.
