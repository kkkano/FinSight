from __future__ import annotations

# ==================== Answer Generation ====================

ANSWER_SYSTEM_PROMPT = """你是 FinSight 的金融分析助手。
你必须只依据给定证据回答，不得引入证据外事实、常识扩写或投资建议。
若证据不足，明确写“依据当前证据无法确认”。
涉及数字时必须保留原始数值、单位和时间锚点。"""


def build_answer_user_prompt(question: str, contexts: list[str]) -> str:
    evidence = "\n\n".join(f"[证据{i+1}] {c}" for i, c in enumerate(contexts))
    return (
        "<evidence_pool>\n"
        f"{evidence}\n"
        "</evidence_pool>\n\n"
        f"问题：{question}\n\n"
        "回答约束：\n"
        "1) 只输出与问题直接相关的事实结论；\n"
        "2) 不得补充证据中没有出现的公司、事件、数字或因果；\n"
        "3) 数字必须与证据一致（含单位/时间）；\n"
        "4) 最多 6 条要点，每条一句；\n"
        "5) 不确定时写“依据当前证据无法确认”。"
    )


# ==================== Keypoint Extraction ====================

KEYPOINT_SYSTEM_PROMPT = """你是评估器。请把标准答案拆解为可核验 keypoints。
只输出 JSON，不要输出额外文本。"""


def build_keypoint_user_prompt(question: str, ground_truth: str) -> str:
    return (
        f"问题：{question}\n\n"
        f"标准答案：{ground_truth}\n\n"
        "输出 JSON：{\"keypoints\":[\"...\"]}\n"
        "要求：\n"
        "1) 仅保留可核验事实；\n"
        "2) 忽略主观建议、情绪化措辞和泛化展望；\n"
        "3) 4-8 条，尽量原子化；\n"
        "4) 涉及数字时保留单位与时间。"
    )


# ==================== Claim Extraction ====================

CLAIM_SYSTEM_PROMPT = """你是评估器。请把答案拆成可核验 claims。
只输出 JSON，不要输出额外文本。"""


def build_claim_user_prompt(answer: str) -> str:
    return (
        f"答案：{answer}\n\n"
        "输出 JSON：{\"claims\":[\"...\"]}\n"
        "要求：\n"
        "1) 仅抽取“可由证据验证”的事实 claim；\n"
        "2) 忽略建议、风险偏好、投资动作、语气词；\n"
        "3) 相同事实只保留一条；\n"
        "4) 总数不超过 12 条；\n"
        "5) 数字 claim 必须保留单位与时间。"
    )


# ==================== Claim Judge ====================

CLAIM_JUDGE_SYSTEM_PROMPT = """你是严谨的事实核验器。
给定 claim 和候选证据，判断支持关系。只输出 JSON。"""


def build_claim_judge_user_prompt(claim: str, evidences: list[str]) -> str:
    evidence = "\n\n".join(f"[证据{i+1}] {e}" for i, e in enumerate(evidences))
    return (
        f"Claim: {claim}\n\n"
        f"{evidence}\n\n"
        "输出 JSON："
        "{\"label\":\"supported|unsupported|contradicted\","
        "\"is_numeric_claim\":true|false,"
        "\"numeric_consistent\":true|false,"
        "\"rationale\":\"...\"}\n"
        "判定规则：\n"
        "1) supported：证据可直接支撑 claim；\n"
        "2) contradicted：证据与 claim 明确冲突；\n"
        "3) unsupported：证据不足以支持；\n"
        "4) is_numeric_claim 仅在存在金额/比例/增速/数量等财务数值时为 true，纯年份/日期不算；\n"
        "5) numeric_consistent 对等价表达视为一致（单位换算、四舍五入、同义百分比）。"
    )


# ==================== Keypoint Judge ====================

KEYPOINT_JUDGE_SYSTEM_PROMPT = """你是覆盖率评估器。
给定 keypoint、答案与证据，判断覆盖情况。只输出 JSON。"""


def build_keypoint_judge_user_prompt(keypoint: str, answer: str, evidences: list[str]) -> str:
    evidence = "\n\n".join(f"[证据{i+1}] {e}" for i, e in enumerate(evidences))
    return (
        f"Keypoint: {keypoint}\n\n"
        f"答案：{answer}\n\n"
        f"{evidence}\n\n"
        "输出 JSON："
        "{\"coverage\":\"covered|partial|missing\","
        "\"context_supported\":true|false,"
        "\"rationale\":\"...\"}\n"
        "判定规则：\n"
        "1) covered：答案完整覆盖 keypoint；\n"
        "2) partial：只覆盖部分事实或缺时间/单位；\n"
        "3) missing：未覆盖；\n"
        "4) context_supported：该 keypoint 在证据中可找到直接支撑。"
    )
