## Tasks

- [x] 1. SDD 提案（本目录）
- [x] 2. tests/test_heartbeat_durable_830.py 红测试：删缓存仍可判 / 缓存篡改以侧车为准 / 注册不能重置史 / log 缺失时向后兼容 / 三写入点落侧车
- [x] 3. 实现：heartbeat.py append_tick_log + evaluate_tick_continuity(log_path)；三写入点 + 三消费者接线
- [ ] 4. 本地质量门：pytest 全量（对照宿主基线）+ ext-scan + deploy_manifest
- [ ] 5. push + PR(--base dev)
