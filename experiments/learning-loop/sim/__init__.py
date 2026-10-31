# -*- coding: utf-8 -*-
"""The declared simulation tier of the learning loop (#936).

Home of the DECLARED-SIM machinery from the 2026-10-31 mock-code
inventory: ``loop_sim`` (v1 simulator), ``loop_sim_v3`` (the #887
battery simulator), ``battery_v3_experiments`` (the battery driver),
and ``counterfactual_analysis`` (the #905 NO-GO research instrument).

Nothing is exported here — every module is imported by path
(``sys.path`` bootstraps add this directory), exactly as before the
relocation. Production faces import zero sim modules.
"""
