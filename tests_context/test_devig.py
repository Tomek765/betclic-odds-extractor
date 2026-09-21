from apex_context_engine.devig import power, shin


def test_power_sums_to_one():
    probs = power([1.80, 2.05])
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0 < p < 1 for p in probs)


def test_shin_sums_to_one():
    probs, z = shin([1.80, 3.50, 4.50])
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0 < p < 1 for p in probs)
    assert 0 <= z < 1
