# Design — phase7-eval-harness
oracle = 10 已知答案例, 每例调 priority_ratio 验证一项核心行为 (VoI 分量 / dispatchable / 确定性)。oracle 确定性先行 → harness 可信; 三臂测量后置 (依赖完整 orchestrator)。
防过度宣称: 判据预注册均值+容差, 非"每次都优"。
