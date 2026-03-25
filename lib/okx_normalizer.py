#!/usr/bin/env python3
"""OKX V5 API → VeriTax 内部标准格式转换层.

VeriTax 内部格式使用 OKX 原生字段名, 统一所有品类(SPOT/SWAP/FUTURES/OPTION/MARGIN)
到同一个数据结构中.
"""
from decimal import Decimal


# ---------------------------------------------------------------------------
# Trade / Fill records
# ---------------------------------------------------------------------------

def normalize_fill(raw: dict) -> dict:
    """OKX V5 fill (from spot/swap/futures/option fills endpoint) → VeriTax trade record.

    OKX V5 fill 字段参考:
      instId, instType, side, sz, fillSz, fillPx, fee, feeCcy,
      ts, tradeId, ordId, pnl, billId, tag, ...
    """
    return {
        "instId": raw["instId"],
        "instType": raw.get("instType", "SPOT"),
        "side": raw["side"],           # "buy" / "sell"
        "fillSz": raw.get("fillSz", raw.get("sz", "0")),
        "fillPx": raw.get("fillPx", raw.get("px", "0")),
        "fee": raw.get("fee", "0"),    # 负数 = 扣除
        "feeCcy": raw.get("feeCcy", ""),
        "ts": int(raw.get("ts", 0)),
        "tradeId": raw.get("tradeId", ""),
        "ordId": raw.get("ordId", ""),
        "pnl": raw.get("pnl", "0"),    # 已实现盈亏 (合约)
    }


# ---------------------------------------------------------------------------
# Account bills (deposits, withdrawals, earn income, funding fees, etc.)
# ---------------------------------------------------------------------------

def normalize_bill(raw: dict) -> dict:
    """OKX V5 bill (from account/bills or bills-archive) → VeriTax bill record.

    OKX V5 bill 字段参考:
      instId, instType, ccy, balChg, bal, sz, fee,
      ts, billId, subType, type, ordId, ...

    type 枚举:  1=Transfer, 2=Trade, 3=Delivery, 4=Auto token conversion,
                5=Liquidation, 6=Margin transfer, 7=Interest deduction,
                8=Funding fee, ...
    """
    return {
        "billId": raw.get("billId", ""),
        "instId": raw.get("instId", ""),
        "instType": raw.get("instType", ""),
        "ccy": raw.get("ccy", ""),
        "balChg": raw.get("balChg", "0"),
        "bal": raw.get("bal", "0"),
        "sz": raw.get("sz", "0"),
        "fee": raw.get("fee", "0"),
        "type": raw.get("type", ""),
        "subType": raw.get("subType", ""),
        "ts": int(raw.get("ts", 0)),
        "ordId": raw.get("ordId", ""),
    }


# ---------------------------------------------------------------------------
# Deposit / Withdrawal records
# ---------------------------------------------------------------------------

def normalize_deposit(raw: dict) -> dict:
    """OKX V5 deposit record → VeriTax deposit record.

    OKX V5 deposit 字段参考:
      amt, ccy, chain, txId, ts, state, depId, from, to, ...
    """
    return {
        "type": "deposit",
        "amt": raw.get("amt", "0"),
        "ccy": raw.get("ccy", ""),
        "chain": raw.get("chain", ""),
        "txId": raw.get("txId", ""),
        "ts": int(raw.get("ts", 0)),
        "fee": "0",
        "state": raw.get("state", ""),
        "depId": raw.get("depId", ""),
    }


def normalize_withdrawal(raw: dict) -> dict:
    """OKX V5 withdrawal record → VeriTax withdrawal record.

    OKX V5 withdrawal 字段参考:
      amt, ccy, chain, txId, ts, fee, state, wdId, from, to, ...
    """
    return {
        "type": "withdrawal",
        "amt": raw.get("amt", "0"),
        "ccy": raw.get("ccy", ""),
        "chain": raw.get("chain", ""),
        "txId": raw.get("txId", ""),
        "ts": int(raw.get("ts", 0)),
        "fee": raw.get("fee", "0"),
        "state": raw.get("state", ""),
        "wdId": raw.get("wdId", ""),
    }


# ---------------------------------------------------------------------------
# Earn records (savings interest, staking, DCD yield)
# ---------------------------------------------------------------------------

def normalize_earn_record(raw: dict, product_type: str = "savings") -> dict:
    """OKX earn balance/order → VeriTax earn record.

    product_type: "savings" | "onchain_staking" | "dcd"
    """
    return {
        "type": f"earn_{product_type}",
        "amt": raw.get("amt", raw.get("earnings", "0")),
        "ccy": raw.get("ccy", ""),
        "ts": int(raw.get("ts", raw.get("uTime", 0))),
        "product": raw.get("productId", raw.get("protocolType", product_type)),
    }


# ---------------------------------------------------------------------------
# Account balance
# ---------------------------------------------------------------------------

def normalize_balance(raw: dict) -> dict:
    """OKX V5 account balance detail → VeriTax balance record.

    OKX V5 balance.details[]:
      ccy, eq, availBal, frozenBal, cashBal, upl, ...
    """
    return {
        "ccy": raw.get("ccy", ""),
        "eq": raw.get("eq", "0"),             # 总权益 (含未实现盈亏)
        "availBal": raw.get("availBal", "0"), # 可用余额
        "frozenBal": raw.get("frozenBal", "0"),
    }


# ---------------------------------------------------------------------------
# Fee rates
# ---------------------------------------------------------------------------

def normalize_fee_rate(raw: dict) -> dict:
    """OKX V5 fee rate → VeriTax fee rate record."""
    return {
        "instType": raw.get("instType", ""),
        "maker": raw.get("maker", "0"),
        "taker": raw.get("taker", "0"),
        "ts": int(raw.get("ts", 0)),
    }
