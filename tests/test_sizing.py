"""The mesh-sizing policy, against the numbers it was derived from.

Every figure here was measured — the maleCNS ladder on 100 strided neurons
(docs/MESH_SIZING.md), the per-neuron cases on the 8-neuron panel of 2026-10-02. They are
in the tests rather than only in the doc so that a change to the policy has to argue with
the evidence rather than merely with an assertion.
"""
import pytest

from vfb_connectomics_import.images.sizing import (
    ACCEPT, OVER_BUDGET, OVER_CEILING, Budget, Ladder,
    admissible, decimate_target, estimate_mb, judge, next_rung, plan)

# The calibrated maleCNS ladder: lod2/lod3 are the 100-neuron medians, lod1 is the figure
# docs/MESH_SIZING.md predicts with, lod0 the APL/DL1 mean.
MALECNS = Ladder(density={0: 1292.0, 1: 196.0, 2: 32.2, 3: 6.78},
                 calibrated_from='100 strided neurons, 2026-09-16', expected_lods=4)
B = Budget()


# ----------------------------------------------------------------------------- the ceiling
def test_ceiling_drops_lod0_and_nothing_else():
    assert admissible(MALECNS, B) == (1, 2, 3)


def test_a_rung_the_publisher_did_not_ship_is_not_offered():
    assert admissible(MALECNS, B, served=[2, 3]) == (2, 3)


# -------------------------------------------------------------------------- choosing a rung
def test_typical_neuron_starts_at_lod1():
    # DL1_adPN_L brain, 4,818.9 um2 -> lod1 predicted 8.50 MB.
    preds, start = plan(4818.9, MALECNS, B)
    assert start == 1
    assert preds[0].lod == 1 and preds[0].fits
    assert preds[0].mb == pytest.approx(8.50, abs=0.05)


def test_large_neuron_starts_below_lod1():
    # APL_R brain, 63,397 um2: lod1 predicts 111.8 MB, lod2 18.4 MB.
    preds, start = plan(63397.0, MALECNS, B)
    assert start == 2
    assert [p.fits for p in preds] == [False, True, True]


def test_the_lod1_valve_engages_at_the_documented_area():
    # 20 MB / 9 B/face / 196 f/um2 = 11,338 um2. Below it lod1, above it lod2.
    assert plan(11_000.0, MALECNS, B)[1] == 1
    assert plan(11_700.0, MALECNS, B)[1] == 2


def test_when_nothing_fits_it_still_starts_somewhere():
    # Far beyond any real neuron; the measurement, not the plan, has to settle it.
    preds, start = plan(5_000_000.0, MALECNS, B)
    assert not any(p.fits for p in preds)
    assert start == 1                       # finest admissible, so stepping down is possible


def test_a_ladder_entirely_above_the_ceiling_plans_nothing():
    dense = Ladder(density={0: 1292.0}, calibrated_from='test')
    assert plan(100.0, dense, B) == ((), None)


# ----------------------------------------------- the measurement, not the prediction, decides
def test_giant_fibre_busts_the_budget_the_prediction_said_it_would_meet():
    """DNp01(GF)_R brain: the case that proves verification is not optional.

    10,663 um2 predicts 18.81 MB at lod1 — a fit. The giant fibre runs at 245 f/um2, so
    the mesh that arrives is 2,612,222 faces = 23.51 MB.
    """
    area = 10_663.0
    preds, start = plan(area, MALECNS, B)
    assert start == 1 and preds[0].fits                     # the prediction says yes
    assert judge(2_612_222, area, B) == OVER_BUDGET         # the measurement says no
    assert next_rung(1, MALECNS, B) == 2
    assert judge(344_344, area, B) == ACCEPT                # lod2, what was actually served


def test_ceiling_is_applied_to_the_measurement():
    """DNp01(GF)_R VNC: 1,411,253 faces over 3,815 um2 = 370 f/um2.

    Within budget at 12.70 MB, so a budget-only rule ships it — which is exactly what
    happened on 2026-10-02. It is 1.85x the ceiling and must be rejected.
    """
    area = 3_815.0
    assert estimate_mb(1_411_253, B) == pytest.approx(12.70, abs=0.01)
    assert judge(1_411_253, area, B) == OVER_CEILING


def test_budget_is_reported_when_both_limits_are_busted():
    assert judge(5_000_000, 1_000.0, B) == OVER_BUDGET


def test_a_normal_mesh_is_accepted():
    assert judge(948_736, 4_818.9, B) == ACCEPT             # DL1 brain, 196.9 f/um2


def test_stepping_down_terminates():
    assert next_rung(3, MALECNS, B) is None


# ------------------------------------------------------------- decimation, for BANC's sake
def test_target_is_capped_by_the_budget_not_just_the_density():
    """The bug: density * area ran uncapped, so this returned ~6 M faces (~50 MB)."""
    area, density = 60_000.0, 100.0
    assert int(density * area) == 6_000_000                 # what it used to ask for
    assert decimate_target(8_000_000, area, density, B) == B.max_faces == 2_222_222


def test_the_cap_lands_on_hemibrains_density():
    """20 MB at 9 B/face over 60,000 um2 is 37 f/um2 — the measured 'displays fine' value."""
    assert B.max_faces / 60_000.0 == pytest.approx(37.0, abs=0.1)


def test_density_binds_for_a_typical_neuron():
    # 2,000 um2 at 100 f/um2 = 200,000 faces, far below the 2.22 M cap.
    assert decimate_target(1_000_000, 2_000.0, 100.0, B) == 200_000


def test_a_mesh_already_below_the_density_target_is_still_capped():
    """The second escape: `target >= 0.95 * n` returned the mesh untouched at any size.

    4 M faces over 60,000 um2 is 67 f/um2 — under the 100 f/um2 target, so the old rule
    kept all 4 M (~36 MB).
    """
    assert decimate_target(4_000_000, 60_000.0, 100.0, B) == B.max_faces


def test_small_meshes_are_left_alone():
    assert decimate_target(500, 10.0, 100.0, B) is None          # below the face floor
    assert decimate_target(100_000, 5_000.0, 100.0, B) is None   # 0.9 MB, under skip_mb


def test_skip_never_lets_an_over_budget_mesh_through():
    """skip_mb must be consulted after the target, or a 'small' mesh could bust the cap."""
    assert B.skip_mb < B.max_mb
    over = B.max_faces + 1_000_000
    assert decimate_target(over, 1e9, 100.0, B) == B.max_faces


def test_density_disabled_still_enforces_the_budget():
    assert decimate_target(5_000_000, 60_000.0, 0.0, B) == B.max_faces


# ------------------------------------------------------------------------- the raw/gzip gap
def test_raw_basis_is_reportable_without_changing_the_policy():
    """The served OBJ is not gzipped on the wire; the budget is still denominated in gzip."""
    faces = 948_736                                          # DL1 brain, as served
    assert estimate_mb(faces, B) == pytest.approx(8.54, abs=0.01)
    assert estimate_mb(faces, B, Budget.RAW_BYTES_PER_FACE) == pytest.approx(33.4, abs=0.2)
    assert judge(faces, 4_818.9, B) == ACCEPT                 # unchanged by the caveat


def test_rebasing_to_raw_would_be_four_times_coarser():
    """Why the budget was not simply rebased: the cap stops meeting the quality floor."""
    raw = Budget(bytes_per_face=Budget.RAW_BYTES_PER_FACE)
    assert raw.max_faces / 60_000.0 == pytest.approx(9.5, abs=0.1)   # vs hemibrain's 37


# ------------------------------------------------------------------------------ guard rails
def test_a_ladder_needs_rungs():
    with pytest.raises(ValueError):
        Ladder(density={}, calibrated_from='test')


def test_a_rung_cannot_have_zero_density():
    with pytest.raises(ValueError):
        Ladder(density={0: 0.0}, calibrated_from='test')
