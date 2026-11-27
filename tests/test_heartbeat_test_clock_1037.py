"""Regression for heartbeat fixtures after a long collection-to-test delay."""
import os
from pathlib import Path
import subprocess
import sys


def test_delayed_collection_keeps_recent_and_stale_verdicts(tmp_path):
    plugin = tmp_path / "delay_plugin.py"
    plugin.write_text(
        '''import builtins
import datetime as real_datetime
import importlib.abc
import importlib.machinery
import sys
import types

clock = [real_datetime.datetime.now(real_datetime.timezone.utc) - real_datetime.timedelta(minutes=61)]
class ControlledDateTime(real_datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

class TargetLoader(importlib.abc.Loader):
    def __init__(self, loader):
        self.loader = loader
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        original_import = builtins.__import__
        datetime_proxy = types.ModuleType("datetime")
        datetime_proxy.__dict__.update(real_datetime.__dict__)
        datetime_proxy.datetime = ControlledDateTime
        def local_import(name, *args, **kwargs):
            if name == "datetime":
                return datetime_proxy
            return original_import(name, *args, **kwargs)
        local_builtins = dict(vars(builtins), __import__=local_import)
        module.__dict__["__builtins__"] = local_builtins
        self.loader.exec_module(module)

class TargetFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in ("test_heartbeat_durable_830", "_heartbeat_1037_baseline_tmp"):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = TargetLoader(spec.loader)
        return spec
sys.meta_path.insert(0, TargetFinder())

def pytest_collection_modifyitems(items):
    import rlvr.liveness
    rlvr.liveness.datetime = ControlledDateTime
    clock[0] += real_datetime.timedelta(minutes=61)
''',
        encoding="utf-8",
    )
    test_file = Path(os.environ.get("HEARTBEAT_CLOCK_TEST_FILE", Path(__file__).with_name("test_heartbeat_durable_830.py")))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "delay_plugin",
         str(test_file) + "::test_no_log_legacy_compat",
         str(test_file) + "::test_tampered_cache_log_wins"],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
