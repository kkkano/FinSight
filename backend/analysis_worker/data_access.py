"""计算容器里的数据表入口；保留原始datasets，帮助代码读取常见返回格式。"""
from __future__ import annotations

TABLE_NAMES = ("earnings_estimate", "eps_trend", "eps_revisions")
SEC_METRICS = ("revenue", "gross_profit", "operating_income", "net_income", "eps", "total_assets",
               "total_liabilities", "cash_and_equivalents", "long_term_debt",
               "operating_cash_flow", "capital_expenditures", "free_cash_flow")


def get_frame(datasets: dict, ref: str | dict | list, table: str | None = None):
    import pandas as pd
    if isinstance(ref, str):
        if ref not in datasets:
            raise KeyError("找不到数据引用：" + ref)
        value = datasets[ref]
    elif isinstance(ref, (dict, list)):
        value = ref
    else:
        raise TypeError("get_frame需要数据引用、数据包或行列表。")
    if table:
        if table == "companyfacts" and isinstance(value, dict) and isinstance(value.get("period_ends"), list):
            pass  # 与inspect_dataset的虚拟财报表名一致，原始平行数组不变。
        elif not isinstance(value, dict) or table not in value:
            raise KeyError("这份资料没有数据表：" + str(table))
        else:
            value = value[table]
    for _ in range(6):
        if isinstance(value, list):
            if value and not all(isinstance(row, dict) for row in value):
                raise ValueError("这份列表不是按行组织的数据表，请直接读取datasets中的原值。")
            return pd.DataFrame(value)
        if not isinstance(value, dict):
            raise ValueError("这份资料是文本或单值，请从datasets读取原值，不能直接转成表格。")
        named = [key for key in TABLE_NAMES if key in value]
        if named and not table:
            if len(named) != 1:
                raise ValueError("资料有多张表，请用get_frame(ref, table=表名)选择：" + ", ".join(named))
            value = value[named[0]]
            continue
        nested = next((value[key] for key in ("rows", "kline_data", "bars", "data", "prices", "historical", "quarterly", "results", "output")
                       if isinstance(value.get(key), (list, dict))), None)
        if nested is not None:
            value = nested
            continue
        if isinstance(value.get("period_ends"), list):
            count = len(value["period_ends"])
            fields = {key: value[key] for key in ("period_ends", "periods", *SEC_METRICS) if key in value}
            metadata = value.get("fact_metadata") or {}
            if (any(not isinstance(rows, list) or len(rows) != count for rows in fields.values())
                    or any(not isinstance(rows, list) or len(rows) != count for rows in metadata.values())):
                raise ValueError("财期与指标数量不一致，请先检查原始数据。")
            frame = pd.DataFrame(fields)
            frame["period_end"] = frame["period_ends"]
            frame["period"] = frame["periods"] if "periods" in frame else frame["period_ends"]
            for key in ("ticker", "market", "source", "source_url", "as_of", "currency", "frequency"):
                if key in value and not isinstance(value[key], (dict, list)):
                    frame[key] = value[key]
            if metadata:
                frame["fact_metadata"] = [{key: rows[index] for key, rows in metadata.items()} for index in range(count)]
            frame.attrs.update({key: value[key] for key in ("ticker", "currency", "source", "as_of", "fact_metadata") if key in value})
            return frame
        if all(not isinstance(item, (dict, list)) for item in value.values()):
            return pd.DataFrame([value])
        raise ValueError("无法确定数据表结构，请先查看datasets中的字段：" + ", ".join(list(value)[:12]))
    raise ValueError("数据嵌套较深，请直接从datasets选择需要的表格。")
