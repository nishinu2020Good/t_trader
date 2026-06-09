# T-Trader

A股做T量化工具，2000元账户日内T+0交易助手。

## 功能

- **股票筛选** — 价格3-18元、振幅≥3%、换手≥5%，评分排序
- **实时监控** — 30秒刷新，做T买入/卖出信号提醒
- **交易追踪** — 盈亏统计、胜率计算
- **飞书推送** — 定时行情推送到飞书机器人
- **语音播报** — TTS语音推送到JARVIS前端

## 文件说明

| 文件 | 用途 |
|------|------|
| `t_trader.py` | 主程序（筛选/监控/盈亏） |
| `feishu_alert.py` | 实时监控 + 飞书推送 |
| `screen_watcher.py` | 屏幕截图 |
| `stock_proxy.py` | 本地数据代理服务 |
| `T_Trader.html` | 网页控制面板 |

## 运行

```bash
pip install requests pandas
python t_trader.py
```

## 注意

- `feishu_config.json` 包含飞书webhook密钥，不提交到版本库
- 交易记录 `trades.csv` 为本地私密文件
# test auto push
