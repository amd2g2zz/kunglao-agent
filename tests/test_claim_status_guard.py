"""v1.9.29 claim-status guard tests: worker self-promotion must be caught."""
import sys, tempfile, pathlib
import worker_budget as wb

def make_register(claims):
    import yaml
    return {'claims': claims}

def test_worker_flip_to_proven_blocked():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / 'claim-register.yaml'
        import yaml
        yaml.safe_dump(make_register([{'id': 'C-1', 'status': 'VERIFIED'}]), open(p, 'w'))
        # worker writes PROVEN into the register
        yaml.safe_dump(make_register([{'id': 'C-1', 'status': 'PROVEN'}]), open(p, 'w'))
        ok, reason = wb.compare_register_change(p, {'C-1': 'VERIFIED'}, 'kunglao-worker')
        assert not ok, 'worker self-promotion must be blocked'
        assert 'SELF-PROMOTION' in reason
    print('PASS  test_worker_flip_to_proven_blocked')

def test_orchestrator_exempt():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / 'claim-register.yaml'
        import yaml
        yaml.safe_dump(make_register([{'id': 'C-1', 'status': 'PROVEN'}]), open(p, 'w'))
        ok, reason = wb.compare_register_change(p, {'C-1': 'VERIFIED'}, 'kunglao-orch')
        assert ok, 'orchestrator must be exempt'
    print('PASS  test_orchestrator_exempt')

def test_open_to_verified_allowed():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / 'claim-register.yaml'
        import yaml
        yaml.safe_dump(make_register([{'id': 'C-1', 'status': 'VERIFIED'}]), open(p, 'w'))
        ok, reason = wb.compare_register_change(p, {'C-1': 'OPEN'}, 'kunglao-worker')
        assert ok, 'OPEN->VERIFIED (non-terminal) must be allowed for worker'
    print('PASS  test_open_to_verified_allowed')

def test_multi_claim_partial():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / 'claim-register.yaml'
        import yaml
        before = {'C-1': 'VERIFIED', 'C-2': 'OPEN'}
        yaml.safe_dump(make_register([{'id': 'C-1', 'status': 'PROVEN'}, {'id': 'C-2', 'status': 'VERIFIED'}]), open(p, 'w'))
        ok, reason = wb.compare_register_change(p, before, 'kunglao-worker')
        assert not ok and 'C-1:VERIFIED->PROVEN' in reason
    print('PASS  test_multi_claim_partial')

test_worker_flip_to_proven_blocked()
test_orchestrator_exempt()
test_open_to_verified_allowed()
test_multi_claim_partial()
print('4/4 guard tests passed')
