import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "skills/rtl-ppa-optimization/scripts/nmaforge_matrix_sim_adapter.py"
SPEC = importlib.util.spec_from_file_location("nmaforge_matrix_sim_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def profile_line(case_id, cycles, prefetch_wait=4, write=3, write_stall=1,
                 legacy_stall=None, productive=None):
    if legacy_stall is None:
        legacy_stall = write_stall
    if productive is None:
        productive = write - write_stall
    mac = cycles - prefetch_wait - write
    return (
        "MATRIX_CORE_PROFILE id={id} max_outstanding=4 a_req=0 a_wait=0 "
        "b_req=0 b_wait=0 bias_req=0 bias_wait=0 prep_mac=0 mac={mac} "
        "write={write} next=0 done=0 error=0 error_drain=0 "
        "prefetch_wait={pf} arbiter_stall=2 response_wait=0 writeback_wait={legacy} "
        "outstanding_highwater=1 fifo_full=0 prefetch_a_req=1 prefetch_a_drain=1 "
        "prefetch_b_req=1 prefetch_b_drain=1 prefetch_overlap=1 "
        "prefetch_completed=1 a_tile_cache_hits=0 total={total} "
        "banked_denial=1 line_denial=1 scalar_denial=0 "
        "prefetch_wait_denial=1 prefetch_wait_fifo_full=0 "
        "prefetch_wait_request_grant=1 prefetch_wait_outstanding_drain=1 "
        "prefetch_wait_handoff_ready=1 prefetch_wait_no_request=0 "
        "write_productive={productive} "
        "writeback_stall={stall} write_protection_error=0"
    ).format(id=case_id, total=cycles, pf=prefetch_wait, write=write,
             mac=mac, productive=productive, legacy=legacy_stall,
             stall=write_stall)


def test_parse_profiles_requires_balanced_prefetch_and_write_attribution():
    log = "\n".join((profile_line(100, 77), profile_line(101, 109)))

    profiles = adapter.parse_profiles(log, {100: 77, 101: 109})

    assert [item["id"] for item in profiles] == [100, 101]
    assert profiles[0]["prefetch_wait_denial"] == 1
    assert profiles[0]["write_productive"] == 2
    assert profiles[0]["writeback_stall"] == profiles[0]["writeback_wait"]
    totals = adapter.sum_profile_fields(profiles)
    assert totals["prefetch_wait_denial"] == 2
    assert totals["write_productive"] == 4


@pytest.mark.parametrize(
    "log,cycles,error",
    [
        (profile_line(100, 77, prefetch_wait=5), {100: 77}, "prefetch-wait attribution"),
        (profile_line(100, 77, write=4, productive=2), {100: 77}, "write attribution"),
        (profile_line(100, 77, write_stall=0, legacy_stall=1), {100: 77},
         "writeback-stall counters"),
        (profile_line(100, 77), {100: 78}, "profile total"),
        (profile_line(100, 77), {101: 77}, "IDs do not match"),
    ],
)
def test_parse_profiles_rejects_unbalanced_or_mismatched_evidence(log, cycles, error):
    with pytest.raises(ValueError, match=error):
        adapter.parse_profiles(log, cycles)


def test_parse_profiles_rejects_missing_attribution_fields():
    log = profile_line(100, 77).replace("line_denial=1 ", "")

    with pytest.raises(ValueError, match="Matrix profile missing fields"):
        adapter.parse_profiles(log, {100: 77})


def test_parse_profiles_rejects_state_cycles_that_do_not_match_workload_total():
    log = profile_line(100, 77).replace("mac=70", "mac=69")

    with pytest.raises(ValueError, match="state-cycle attribution"):
        adapter.parse_profiles(log, {100: 77})
