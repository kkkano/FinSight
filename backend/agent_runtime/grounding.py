"""引用按实际使用绑定；数值验证不把全部来源自动授予每个段落。"""
from __future__ import annotations
import re
from urllib.parse import parse_qsl, urlsplit
from .context import dumps
from .data import RunData
from backend.research.grounded_quantities import validate_grounded_quantities


def _directional_quantities(text: str) -> tuple[str, list[str]]:
    """方向词可以表示负数的绝对幅度；不改变目标价、日期或下跌期数。"""
    pattern = re.compile(r"(?<!涨)(?P<direction>下跌|跌幅|下滑|减少|下降|回落|亏损|上涨|涨幅|增加|增长|上升|跌|涨)"
        r"(?P<spacing>\s*(?:了|约|近|接近|大约|约为|幅度为|幅度约|为)?\s*)(?P<symbol>[$￥¥]?)\s*"
        r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)(?P<unit>\s*(?:万亿|千亿|十亿|千万|百万|亿|万)?(?:美元|港元|人民币|欧元|英镑|元|USD|HKD|CNY|EUR|GBP|%|％))?", re.I)
    issues = []
    negative = {"下跌", "跌幅", "下滑", "减少", "下降", "回落", "亏损", "跌", "暴跌", "大跌", "急跌"}
    def normalize(match):
        if not match["symbol"] and not match["unit"]:
            return match[0]
        number = match["number"]
        if match["direction"] in negative:
            if number.startswith("+"):
                issues.append("explanation_direction_mismatch")
            number = "-" + number.lstrip("-+")
        elif number.startswith("-"):
            issues.append("explanation_direction_mismatch")
        return match["direction"] + match["spacing"] + match["symbol"] + number + (match["unit"] or "")
    text = pattern.sub(normalize, text)
    # 英文来源的跌幅常写正的绝对幅度；只在紧邻百分数的明确方向词处补符号。
    negative_words = r"falls?|fell|fallen|drops?|dropped|declines?|declined|plunges?|plunged|cratered|sinks?|sank|down|loss(?:es)?"
    positive_words = r"rises?|rose|risen|gains?|gained|increases?|increased|grew|growth|up|soars?|soared"
    english = re.compile(r"\b(?P<direction>" + negative_words + "|" + positive_words + r")\b"
        r"(?P<spacing>\s+(?:(?:by|of|approximately|nearly|about|around|over|more\s+than)\s+)*)"
        r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)(?P<unit>\s*[%％])"
        r"(?P<continuations>(?:\s+(?:in\s+(?:19|20)\d{2}\s+)?and\s+"
        r"(?:approximately\s+|about\s+)?\d[\d,]*(?:\.\d+)?\s*[%％]){0,2})", re.I)
    def english_normalize(match):
        negative_direction = bool(re.fullmatch(negative_words, match["direction"], re.I))
        number = match["number"]
        if negative_direction:
            if number.startswith("+"):
                issues.append("explanation_direction_mismatch")
            number = "-" + number.lstrip("-+")
        elif number.startswith("-"):
            issues.append("explanation_direction_mismatch")
        def coordinated_number(child):
            value = child[1]
            if negative_direction:
                if value.startswith("+"):
                    issues.append("explanation_direction_mismatch")
                value = "-" + value.lstrip("-+")
            elif value.startswith("-"):
                issues.append("explanation_direction_mismatch")
            return value + child[2]
        continuations = re.sub(r"([-+]?\d[\d,]*(?:\.\d+)?)(\s*[%％])", coordinated_number, match["continuations"])
        return match["direction"] + match["spacing"] + number + match["unit"] + continuations
    text = english.sub(english_normalize, text)
    suffix = re.compile(r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)(?P<unit>\s*[%％])"
                        r"(?P<spacing>\s+)(?P<direction>plunge|decline|drop|fall|loss|sell-off)\b", re.I)
    def suffix_normalize(match):
        if match["number"].startswith("+"):
            issues.append("explanation_direction_mismatch")
        return "-" + match["number"].lstrip("-+") + match["unit"] + match["spacing"] + match["direction"]
    text = suffix.sub(suffix_normalize, text)
    chinese_suffix = re.compile(r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)(?P<unit>\s*[%％])"
        r"(?P<spacing>\s*(?:的|这个)?\s*(?:急剧|显著|大幅|单日)?\s*)"
        r"(?P<direction>暴跌|大跌|急跌|下跌|跌幅|下滑|减少|下降|回落|亏损|暴涨|大涨|上涨|涨幅|增加|增长|上升)"
        r"(?!\s*(?:概率|风险|可能性|机会))")
    def chinese_suffix_normalize(match):
        number = match["number"]
        if match["direction"] in negative:
            if number.startswith("+"):
                issues.append("explanation_direction_mismatch")
            number = "-" + number.lstrip("-+")
        elif number.startswith("-"):
            issues.append("explanation_direction_mismatch")
        return number + match["unit"] + match["spacing"] + match["direction"]
    text = chinese_suffix.sub(chinese_suffix_normalize, text)
    return text, list(dict.fromkeys(issues))


def _definition_quantities(text: str) -> str:
    """滚动均值的窗口与空值期数属于公式定义，不把市场金额或涨跌幅豁免。"""
    windows = {int(value) for value in re.findall(r"(?<![A-Za-z0-9_])rolling\(\s*(\d{1,3})\s*\)\s*\.mean\(\s*\)", text)
               if 1 <= int(value) <= 252}
    windows.update(int(match[1]) for match in re.finditer(r"[‘'“\"]?(\d{1,3})[’'”\"]?\s*(?:指|表示)(?:的是)?\s*\1\s*个?交易日", text)
                   if 1 <= int(match[1]) <= 252)
    # 指标名称里的窗口号是方法标签，空值数量与观察值仍单独核验。
    text = re.sub(r"(?<!\d)\d{1,3}(?=\s*日均线)", "窗口期数", text)
    if not windows:
        return text
    text = re.sub(r"(?<![A-Za-z0-9_])rolling\(\s*\d{1,3}\s*\)\s*\.mean\(\s*\)", "滚动算术平均", text)
    for window in windows:
        for number in {window, window - 1}:
            text = re.sub(r"(?<![\d.])" + str(number) + r"(?=\s*(?:个(?:收盘价|数据点|交易日|日历日|自然日|点)|日均线|个?交易日))", "窗口期数", text)
        text = re.sub(r"(?<![\d.])" + str(window) + r"(?=[’'”\"]?\s*(?:指|表示)(?:的是)?\s*窗口期数)", "窗口期数", text)
    return text


def _referenced_records(refs: list[str], data: RunData) -> set[str]:
    """引用一个真实计算结果，也能回溯其输入；不授权无关资料或其它计算。"""
    result = set()
    def visit(ref):
        record = data.records.get(ref, {})
        if ref in result or record.get("status") != "success":
            return
        result.add(ref)
        inputs = record.get("inputs") or {}
        for parent in inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else []):
            visit(parent)
    for sid in refs:
        visit(data.sources.get(sid, {}).get("data_ref"))
    return result


def chart_coverages(data: RunData, refs: list[str] | None = None):
    authorized = _referenced_records(refs or [], data)
    seen = set()
    artifacts = list(getattr(data, "prior_artifacts", [])) + list(data.artifacts)
    for artifact in reversed(artifacts):
        if refs:
            lineage = _referenced_records(artifact.get("source_refs") or [], data)
            leaves = {ref for ref in lineage if not ((data.records[ref].get("inputs") or {}).get("dataset_refs")
                      or (data.records[ref].get("inputs") or {}).get("dataset_ref"))}
            if not leaves or not leaves.issubset(authorized):
                continue
        for series in artifact.get("spec", {}).get("series", []):
            field = series["field"]
            lineage = _referenced_records(artifact.get("source_refs") or [], data)
            subjects = tuple(sorted({str(data.records[ref].get("inputs", {}).get("ticker")) for ref in lineage
                if data.records[ref].get("inputs", {}).get("ticker")}))
            identity = (subjects, field)
            if identity in seen:
                continue
            coverage = (artifact.get("coverage") or {}).get(field)
            if not coverage:
                rows = artifact.get("data", {}).get("rows", [])
                # 旧图投影没有coverage时，只回读其实际绘图dataset与table，不猜其它表。
                if not rows and len(artifact.get("dataset_refs") or []) == 1:
                    ref = artifact["dataset_refs"][0]
                    if data.records.get(ref, {}).get("status") == "success":
                        try:
                            rows = data.rows(ref, table=artifact.get("spec", {}).get("table"))
                        except ValueError:
                            rows = []
                valid = [index for index, row in enumerate(rows) if row.get(field) is not None]
                if not rows:
                    continue
                x = artifact["spec"]["x"]
                coverage = {"points": len(rows), "valid": len(valid), "missing": len(rows)-len(valid),
                    "leading_missing": valid[0] if valid else len(rows),
                    "first_valid": rows[valid[0]].get(x) if valid else None,
                    "last_valid": rows[valid[-1]].get(x) if valid else None}
            seen.add(identity)
            yield artifact, series, coverage


def _coverage_violations(text: str, data: RunData, refs: list[str]) -> list[str]:
    plain = re.sub(r"[*`_]", "", text)
    if "均线" not in plain and not re.search(r"\b(?:ma|sma)\d+\b", plain, re.I):
        return []
    claims = re.findall(r"(?:前|最早)\s*(\d+)\s*(?:个)?(?:天|个?交易日|个?数据点|个?点).{0,20}(?:无法计算|不足|为空|没有|缺失|不可用)", plain)
    first_dates = re.findall(r"(?:从|始于|自)\s*(\d{4}-\d{2}-\d{2}).{0,16}(?:开始有值|开始可用|均线有值)", plain)
    for artifact, series, coverage in chart_coverages(data, refs):
        label = str(series.get("name") or series["field"])
        if "均线" not in label and not re.fullmatch(r"(?:ma|sma)\d+", series["field"], re.I):
            continue
        window = re.search(r"\d+", label + " " + series["field"])
        if window and not re.search(r"(?<!\d)" + window[0] + r"\s*(?:日均线|个交易日|交易日)|(?:ma|sma)" + window[0], plain, re.I):
            continue
        if claims and any(int(count) != coverage["leading_missing"] for count in claims):
            return ["explanation_chart_coverage_mismatch"]
        if first_dates and any(day != str(coverage.get("first_valid") or "")[:10] for day in first_dates):
            return ["explanation_chart_coverage_mismatch"]
    return []


_FINANCIAL_RATIO_FIELDS = {"gross_margin", "operating_margin", "net_margin", "fcf_margin",
                           "liabilities_to_assets", "liab_to_assets", "fcf_yield", "fcf_yield_on_mcap"}


def _percent_values(data: RunData, refs: list[str]) -> list[float]:
    """百分数只匹配明确百分比/变化比例字段；样本数不能碰巧充当涨幅。"""
    authorized = _referenced_records(refs, data) if refs else set(data.records)
    values = []
    def collect(value, kind="", percent_unit=False, ratio_scale=None):
        if isinstance(value, str):
            signed, _ = _directional_quantities(value.replace("−", "-"))
            values.extend(float(number.replace(",", ""))/100 for number in re.findall(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*[%％]", signed))
        elif isinstance(value, list):
            for child in value:
                collect(child, kind, percent_unit, ratio_scale)
        elif isinstance(value, dict):
            kind = (value.get("method") or {}).get("kind", kind) if isinstance(value.get("method"), dict) else kind
            unit = value.get("unit") or value.get("units")
            if isinstance(unit, str):
                percent_unit = unit.lower() in {"%", "percent", "percentage", "percentage points"}
            fields = {series["field"] for series in value.get("series", [])
                      if isinstance(series, dict) and series.get("unit") == "%" and series.get("field")}
            for row in value.get("rows", []) if isinstance(value.get("rows"), list) else []:
                if isinstance(row, dict):
                    values.extend(float(row[field])/100 for field in fields if type(row.get(field)) in {int, float})
            for key, child in value.items():
                if key in {"code", "code_hash", "input_hash"}:
                    continue
                if type(child) in {int, float}:
                    if key in {"return_ratio", "change_ratio", "growth_ratio"} or key == "return_pct" and kind == "consecutive_decline_streaks":
                        values.append(float(child))
                    elif key.endswith(("_pct", "_percent")) or key == "value" and percent_unit:
                        values.append(float(child)/100)
                    elif key in _FINANCIAL_RATIO_FIELDS:
                        values.append(float(child) * (ratio_scale if ratio_scale is not None else .01 if percent_unit else 1))
                elif key == "value" and percent_unit and isinstance(child, str) and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", child):
                    values.append(float(child)/100)
                else:
                    collect(child, kind, percent_unit, .01 if key in {"ratios_pct", "ratios_percent"} else ratio_scale)
    for ref, record in data.records.items():
        if record.get("status") != "success":
            continue
        inputs = record.get("inputs") or {}
        parents = inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else [])
        if ref in authorized or (record.get("tool") in {"analyze_dataset", "run_analysis_code"} and parents and all(parent in authorized for parent in parents)):
            collect(record.get("output"))
    return values


def _scaled_money_notes(value) -> list[str]:
    """计算字段明确声明了币种和倍率时补等值单位，不猜只写 USD 的字段其实用了十亿。"""
    notes = []
    if isinstance(value, dict):
        for key, child in value.items():
            match = re.search(r"(?:^|_)(usd|hkd|cny|eur|gbp)_(mn|bn|tn|100mn)$", key, re.I)
            if match and type(child) in {int, float}:
                unit = {"mn": "M", "bn": "B", "tn": "T", "100mn": "亿"}[match[2].lower()]
                notes.append(f"{child} {unit} {match[1].upper()}")
            elif isinstance(child, (dict, list)):
                notes.extend(_scaled_money_notes(child))
    elif isinstance(value, list):
        for child in value:
            notes.extend(_scaled_money_notes(child))
    return notes


def checked_comparison_stats(record: dict) -> dict:
    """旧原生比较按真实序列复核；不把模型自写统计或起点分离当作交叉。"""
    output = record.get("output") or {}
    stats = output.get("comparison_stats") or {}
    if ("crossovers" not in stats and record.get("tool") == "analyze_dataset"
            and (output.get("method") or {}).get("kind") == "price_return_comparison"):
        from .analysis import comparison_crossovers
        stats = {**stats, "crossovers": comparison_crossovers(output.get("rows") or [], output.get("series") or [])}
    return stats


def _crossover_violations(text: str, crossovers: list[dict]) -> list[str]:
    for clause in re.split(r"[\n。；;!?！？]", text):
        counts = re.findall(r"(?:交叉|交汇|领先换手)(?:次数)?[^\d。]{0,12}(\d+)\s*次", clause)
        last_dates = re.findall(r"最后(?:一次)?(?:交叉|交汇|领先换手).{0,12}?(\d{4}-\d{2}-\d{2})", clause)
        if not counts and not last_dates:
            continue
        pairs = [pair for pair in crossovers if all(re.search(r"(?<![A-Za-z0-9])"+re.escape(pair[name])+r"(?![A-Za-z0-9])",clause,re.I) for name in ("left","right"))]
        if not pairs and len(crossovers) == 1:
            pairs = crossovers
        if len(pairs) != 1:
            return ["explanation_comparison_pair_unverified"]
        pair = pairs[0]
        if any(int(count) != pair["count"] for count in counts):
            return ["explanation_crossover_mismatch"]
        dates = pair.get("dates") or []
        if any(not dates or day != str(dates[-1])[:10] for day in last_dates):
            return ["explanation_crossover_mismatch"]
    return []


def _period_trend_violations(text: str, data: RunData, refs: list[str]) -> list[str]:
    """两个观测只有一次相邻变化，不能冒充两个期间各自增长。"""
    plain = re.sub(r"[*`_]", "", text)
    claims = list(re.finditer(r"(?P<count>(?<![A-Za-z0-9第])\d+个?|(?<!第)(?:两(?:个)?|二个|三个))\s*(?:已公布(?:的)?|已披露(?:的)?|最新的?)?\s*(?:财季|季度|季|期间|期|交易日|月份).{0,18}?(?:均为增长|均增长|均上涨|都增长|都上涨)", plain))
    if not claims:
        return []
    authorized = _referenced_records(refs, data) if refs else set(data.records)
    aliases = {"revenue":r"营收|收入|revenue", "gross_profit":r"毛利|gross.profit", "net_income":r"净利润|net.income", "close":r"股价|收盘价|close", "eps":r"每股收益|EPS"}
    known = {str(record.get("inputs",{}).get("ticker")) for record in data.records.values() if record.get("inputs",{}).get("ticker")}
    mentioned = {ticker for ticker in known if re.search(r"(?<![A-Za-z0-9])"+re.escape(ticker)+r"(?![A-Za-z0-9])",plain,re.I)}
    for ref, record in reversed(list(data.records.items())):
        output = record.get("output")
        if record.get("status") != "success" or record.get("tool") != "analyze_dataset" or not isinstance(output,dict):
            continue
        method = output.get("method") or {}
        if method.get("kind") != "series_statistics" or not output.get("rows"):
            continue
        parents = (record.get("inputs") or {}).get("dataset_refs") or [(record.get("inputs") or {}).get("dataset_ref")]
        if refs and ref not in authorized and not all(parent in authorized for parent in parents if parent):
            continue
        lineage = _referenced_records(data.source_refs(ref),data)
        subjects = {str(data.records[key].get("inputs",{}).get("ticker")) for key in lineage if data.records[key].get("inputs",{}).get("ticker")}
        if mentioned and not mentioned.issubset(subjects) or not refs and not mentioned and len(known)>1:
            continue
        field = method.get("field", "")
        if not field:
            continue
        for claim in claims:
            fragment = claim[0]
            if not re.search(aliases.get(field,re.escape(field)),fragment,re.I) or re.search(r"同比|与|和|及|、|不能|无法|不代表|并非|不都|不均",fragment):
                continue
            prefix = plain[max(0,claim.start()-15):claim.start()]
            if re.search(r"不能|无法|不代表|并非",prefix):
                continue
            token = claim["count"].rstrip("个")
            count = int(token) if token.isdigit() else 3 if token.startswith("三") else 2
            if count > int(output["rows"][0].get("observations") or 0)-1:
                return ["explanation_period_trend_unverified"]
    return []


def _comparison_violations(text: str, data: RunData, refs: list[str]) -> list[str]:
    """绝对路径结论必须由同一来源的比较统计支持，不能只依据期末涨幅。"""
    plain = re.sub(r"[*`_]", "", text)
    issues = []
    authorized = _referenced_records(refs, data)
    seen = set()
    for ref, record in reversed(list(data.records.items())):
        output = record.get("output")
        if record.get("status") != "success" or not isinstance(output, dict) or not output.get("comparison_stats"):
            continue
        parents = (record.get("inputs") or {}).get("dataset_refs") or [(record.get("inputs") or {}).get("dataset_ref")]
        if refs:
            inputs_bound = any(parents) and all(parent in authorized for parent in parents if parent)
            if not inputs_bound and ref not in authorized:
                continue
        stats = checked_comparison_stats(record)
        observations = stats.get("observations")
        lead_days = stats.get("lead_days") or {}
        series_stats = stats.get("series") or {}
        subjects = tuple(sorted(series_stats))
        if subjects in seen:
            continue
        seen.add(subjects)
        crossovers = stats.get("crossovers") or []
        if crossovers:
            issues.extend(_crossover_violations(plain, crossovers))
        for ticker in series_stats:
            if not re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", plain, re.I):
                continue
            sentences = [sentence for sentence in re.split(r"[。！!?？\n]", plain)
                         if re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", sentence, re.I)]
            for sentence in sentences:
                subject_pattern = r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])"
                first_subject = re.search(subject_pattern, sentence, re.I)
                if re.search(r"(?:不能|无法|不代表|不保证|不足以|并非).{0,8}$", sentence[:first_subject.start()]):
                    continue
                fragment = sentence[first_subject.end():]
                other_pattern = "|".join(re.escape(name) for name in series_stats if name != ticker)
                other = re.search(r"(?<![A-Za-z0-9])(?:" + other_pattern + r")(?![A-Za-z0-9])", fragment, re.I) if other_pattern else None
                fragment = fragment[:other.start()] if other else fragment
                if re.search(r"(?:全年|始终|一直|每天|每个交易日).{0,12}(?:领先|跑赢)|(?:领先|跑赢).{0,12}(?:全年保持|始终|一直)", fragment):
                    others = [count for name, count in lead_days.items() if name not in {ticker, "tie"}]
                    if observations and (lead_days.get(ticker, 0) < observations or not others or any(count > 0 for count in others)):
                        issues.append("explanation_comparison_path_mismatch")
                if re.search(subject_pattern + r"\s*从未.{0,20}反超|未(?:曾)?出现\s*" + subject_pattern + r".{0,20}反超", sentence, re.I):
                    if lead_days.get(ticker, 0) > 0:
                        issues.append("explanation_comparison_path_mismatch")
                if (re.search(r"(?:全年|持续|一直|始终|每天).{0,12}(?:上行|向上|上涨|增长)", fragment)
                        and not re.search(r"(?:未|不|没有|并非).{0,10}(?:全年|持续|一直|始终|每天)", fragment)):
                    if not (stats.get("strictly_increasing") or {}).get(ticker, False):
                        issues.append("explanation_comparison_path_mismatch")
    return list(dict.fromkeys(issues))


def _metadata_violations(text: str, data: RunData, refs: list[str]) -> list[str]:
    plain = re.sub(r"[*`_]", "", text)
    selected = {data.sources[sid].get("data_ref") for sid in refs} if refs else set(data.records)
    visited, payloads, tickers = set(), [], set()
    def collect(ref):
        if ref in visited:
            return
        visited.add(ref)
        record = data.records.get(ref, {})
        if record.get("status") != "success":
            return
        inputs = record.get("inputs") or {}
        if inputs.get("ticker"):
            tickers.add(str(inputs["ticker"]))
        output = record.get("output")
        if isinstance(output, dict):
            payloads.extend(value for value in (output, output.get("asset"), output.get("meta"), output.get("method"), output.get("data")) if isinstance(value, dict))
        elif record.get("tool") == "get_stock_price" and isinstance(output, str):
            fields = {key.strip(): value.strip() for key, value in re.findall(r"(?:^|\|)\s*([^|:]+):\s*([^|]+)", output)}
            quote = {"source_format": "formatted_quote"}
            for name, key in {"Session":"session", "Time precision":"time_precision", "Price basis":"price_basis",
                              "Currency":"currency", "Exchange":"exchange"}.items():
                if name in fields:
                    quote[key] = fields[name]
            dividends = fields.get("Dividends included", "").lower()
            if dividends in {"true", "false"}:
                quote["dividends_included"] = dividends == "true"
            payloads.append(quote)
        for parent in inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else []):
            collect(parent)
    for ref in selected:
        collect(ref)
    if not payloads:
        return []
    realtime_claims = list(re.finditer(r"实时(?:的)?(?:报价|价格|行情|数据包?|逐笔(?:成交)?数据)", plain))
    realtime_claim = any(not re.search(r"(?:非|不是|并非|不代表|不能(?:当作|视为)|没有|未能获取|拿不到|不提供)[^。；\n]{0,12}$",
                            plain[max(0, match.start()-24):match.start()]) for match in realtime_claims)
    if realtime_claim and not any(payload.get("is_realtime") is True or payload.get("realtime") is True for payload in payloads):
        return ["explanation_realtime_unverified"]
    delays = []
    for payload in payloads:
        for key, scale in (("delay_seconds", 1), ("delay_minutes", 60), ("exchangeDataDelayedBy", 60)):
            if type(payload.get(key)) in {int, float}:
                delays.append(float(payload[key]) * scale)
    delay_pattern = (r"(?:延迟|滞后)\s*(?:约)?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时|天)"
                     r"|(?:约)?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时|天)\s*(?:延迟|滞后)")
    for match in re.finditer(delay_pattern, plain):
        number, unit = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        claimed = float(number) * {"秒": 1, "分钟": 60, "小时": 3600, "天": 86400}[unit]
        if not any(abs(claimed - delay) <= 1 for delay in delays):
            return ["explanation_delivery_delay_unverified"]
    adjustment_claim = re.search(r"(?:本图|本次|这些数据|数据为|价格为|价格是|用的是|采用了|使用了)[^\n。]{0,35}(?:未(?:经)?复权|未调整收盘价)", plain)
    if adjustment_claim:
        bases = {str(payload.get("price_basis") or "").lower() for payload in payloads} - {"", "unknown"}
        if not bases or not bases.issubset({"unadjusted", "unadjusted_close", "raw_close"}):
            return ["explanation_adjustment_unverified"]
    if re.search(r"未(?:计入|包含)(?:现金)?(?:分红|股息)", plain):
        flags = [payload.get("dividends_included") for payload in payloads if type(payload.get("dividends_included")) is bool]
        if not flags or any(flags):
            return ["explanation_adjustment_unverified"]
    if any(re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", plain, re.I) for ticker in tickers):
        mentioned = {name for name, pattern in {"NYSE": r"\bNYSE\b|纽约证券交易所|纽交所", "NASDAQ": r"\bNASDAQ\b|纳斯达克"}.items() if re.search(pattern, plain, re.I)}
        supplied = set()
        for payload in payloads:
            value = str(payload.get("exchange") or payload.get("fullExchangeName") or "").upper()
            if value in {"NYSE", "NYQ"} or "NEW YORK STOCK" in value:
                supplied.add("NYSE")
            if value in {"NMS", "NGM", "NCM"} or "NASDAQ" in value:
                supplied.add("NASDAQ")
        if not mentioned.issubset(supplied):
            return ["explanation_exchange_unverified"]
    return []


def _source_url_identity(url: str) -> tuple:
    """只忽略明确跟踪参数；页面路径、身份参数和片段必须仍然相同。"""
    parsed = urlsplit(url)
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
                "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", ".tsrc"}
    def is_tracking(key, value):
        key = key.lower()
        return key in tracking or key == "ref" and value.lower() == "yahoofinance" or (
            key == "tlnk" and value.startswith("yf-"))
    query = tuple(sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                         if not is_tracking(key, value)))
    return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, parsed.fragment


def source_urls(text: str, data: RunData) -> list[str]:
    """识别链接与其后的标点/角标，不把已知链接当作任意路径的前缀许可。"""
    known_urls = {source.get("url") for source in data.sources.values() if source.get("url")}
    boundaries = ").,，。；;）（[]}`'\""
    result = []
    for token in re.findall(r"https?://[^\s<>]+", text):
        matched = next((url for url in known_urls if token == url or
                        token.startswith(url) and (token[len(url):len(url)+1] in ")(（[]}`'\"，。；"
                        or all(char in boundaries for char in token[len(url):]))), None)
        candidate = token.rstrip(boundaries)
        if not matched:
            matched = next((url for url in known_urls if _source_url_identity(url) == _source_url_identity(candidate)), None)
        # 等价链接回绑实际保存的URL，使交付和服务端引用检查使用同一原始来源。
        result.append(matched or candidate)
    return result


def cited_sources(text: str, data: RunData) -> list[str]:
    urls = set(source_urls(text, data))
    return [sid for sid, source in data.sources.items()
            if ("[" + sid + "]") in text or ("[^" + sid + "]") in text
            or bool(source.get("url") and source["url"] in urls)]


def validate_paragraph(text: str, data: RunData, *, require_citations: bool = False) -> list[str]:
    refs = cited_sources(text, data)
    clean = re.sub(r"\[([^\]]*)\]\(https?://[^)]+\)", r"\1", text)
    clean = re.sub(r"https?://\S+|\[\^?S[a-f0-9]+\]", "", clean)
    clean = re.sub(r"(?m)^#{1,6}\s+.*$", "", clean)
    clean = re.sub(r"[*`]", "", clean)
    clean = clean.replace("−", "-").replace("﹣", "-")
    absence = re.search(r"(?:没有|不存在|未发生|未发现|并无|暂无).{0,16}(?:事件|新闻|催化)|\bno\s+(?:material\s+)?(?:news|events?|catalysts?)\b", clean, re.I)
    if absence and not re.search(r"本轮|返回|已读取|检索范围|未能获取|就现有证据|在已取得(?:的)?(?:资料|证据|报道)中", clean):
        windows = []
        for record in data.records.values():
            output = record.get("output")
            if isinstance(output, dict):
                windows.append(output.get("coverage_window") or {})
        if not any(w.get("exhaustive") is True and w.get("scope") != "returned_articles" for w in windows if isinstance(w, dict)):
            return ["explanation_unsupported_window_absence"]
    metadata_violations = _metadata_violations(clean, data, refs)
    if metadata_violations:
        return metadata_violations
    comparison_violations = _comparison_violations(clean, data, refs)
    if comparison_violations:
        return comparison_violations
    trend_violations = _period_trend_violations(clean, data, refs)
    if trend_violations:
        return trend_violations
    coverage_violations = _coverage_violations(clean, data, refs)
    if coverage_violations:
        return coverage_violations
    clean, direction_violations = _directional_quantities(clean)
    if direction_violations:
        return direction_violations
    clean = _definition_quantities(clean)
    if not re.search(r"\d", clean) or re.search(r"假设|示意|例如|情景假定", clean):
        return []
    if require_citations and not refs:
        return ["missing_factual_citation"]
    # 普通短答未标inline引用时也要以本轮真实数据核对数值；报告要求明确逐段绑定。
    selected = [data.sources[sid] for sid in refs] if refs else list(data.sources.values())
    raw = []
    def period_notes(ref, seen=None):
        seen = set() if seen is None else seen
        if ref in seen:
            return []
        seen.add(ref)
        record = data.records.get(ref, {})
        output = record.get("output")
        notes = []
        if isinstance(output, dict):
            for key in ("period", "interval"):
                match = re.fullmatch(r"(\d+)(d|wk|mo|y)", str(output.get(key) or ""))
                if match:
                    notes.append(match.group(1) + {"d": "天", "wk": "周", "mo": "月", "y": "年"}[match.group(2)])
        inputs = record.get("inputs") or {}
        parents = inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else [])
        for parent in parents:
            notes.extend(period_notes(parent, seen))
        return notes
    currencies: set[str] = set()
    def collect_currency(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"currency", "reporting_currency", "trading_currency"} and isinstance(child, str):
                    currencies.add(child.upper())
                elif isinstance(child, (dict, list)):
                    collect_currency(child)
        elif isinstance(value, list):
            for child in value:
                collect_currency(child)
    recorded_refs = set()
    def append_record(ref):
        record = data.records.get(ref, {})
        if ref in recorded_refs or record.get("status") != "success":
            return
        recorded_refs.add(ref)
        collect_currency(record["output"])
        grounded_output = record["output"]
        if isinstance(grounded_output, dict) and isinstance(grounded_output.get("method"), dict):
            grounded_output = {**grounded_output, "method": {key: value for key, value in grounded_output["method"].items()
                               if key not in {"code", "code_hash", "input_hash"}}}
        normalized = re.sub(r"(?<=\d)T(?=\d)", " ", dumps(grounded_output))
        normalized = re.sub(r"(?<=\d)Z\b", " UTC", normalized)
        raw.append(normalized)
        raw.extend(_scaled_money_notes(grounded_output))
        raw.extend(period_notes(ref))
    for source in selected:
        meta = source.get("metadata") or source.get("meta") or {}
        if meta.get("subject_binding") == "unverified":
            return ["unverified_subject_reference"]
        append_record(source.get("data_ref"))
    if refs:
        # 正文可以引用原始行情来源；已由确定性工具算出的派生量仍需完整绑定这些来源。
        # 只纳入有实际计算记录且所有输入均被当前段落引用的结果，不把其它标的计算结果混入。
        authorized = _referenced_records(refs, data)
        # 真实计算引用包含其声明的输入；否则计算段落回述输入金额会被误判为无依据。
        for parent_ref in authorized:
            append_record(parent_ref)
        for computed_ref, record in data.records.items():
            if record.get("tool") not in {"analyze_dataset", "run_analysis_code"} or record.get("status") != "success":
                continue
            inputs = record.get("inputs") or {}
            parents = inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else [])
            if parents and all(parent in authorized for parent in parents):
                append_record(computed_ref)
    raw.extend(dumps(coverage) for _, _, coverage in chart_coverages(data, refs))
    if not raw:
        # 概念解释和明确假设已在上方处理；无来源的事实数字不能当作已核验结论交付。
        return ["missing_factual_evidence"]
    mentioned = {code for code, pattern in {"USD": r"美元|美金|\bUSD\b", "HKD": r"港元|港币|\bHKD\b",
                 "CNY": r"人民币|\b(?:CNY|RMB)\b", "EUR": r"欧元|\bEUR\b", "GBP": r"英镑|\bGBP\b"}.items()
                 if re.search(pattern, clean, re.I)}
    if currencies and not mentioned.issubset(currencies):
        return ["explanation_currency_mismatch"]
    percentages = re.findall(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*[%％]", clean)
    if percentages:
        available_percentages = _percent_values(data, refs)
        for token in percentages:
            token = token.replace(",", "")
            places = len(token.split(".", 1)[1]) if "." in token else 0
            tolerance = max(1e-9, .5 * 10**(-places) / 100)
            if not any(abs(float(token)/100-value) <= tolerance for value in available_percentages):
                return ["explanation_contains_unbound_number"]
    try:
        # 百分数已按明确单位单独核验；不让数量/价格字段碰巧匹配它，也不扩大通用数值池。
        numeric_text = re.sub(r"[-+]?\d[\d,]*(?:\.\d+)?\s*[%％]", "", clean)
        validate_grounded_quantities(numeric_text, "\n".join(raw))
    except ValueError as exc:
        return [str(exc)]
    return []

