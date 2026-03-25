#!/usr/bin/env python3
"""VeriTax Demo 菜单 — 确定性输出服务选择菜单。
Flash 应 exec 此脚本，然后 verbatim 转发输出给用户。
"""

MENU_TEXT = """\
🦞 Demo 数据已就绪。请选择服务类型：

(A) 一次性税务审查（扫描→合规计算→TLH分析→审计证明）
(B) Continuous Mode 持续监控 Demo（模拟多天：每日增量扫描 + 每小时TLH监控 + 闪崩触发）

请回复 A 或 B："""

if __name__ == "__main__":
    print(MENU_TEXT)
