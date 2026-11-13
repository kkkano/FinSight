"""只解析整数引用协议并查来源表，不判断自然语言结论。"""
import re


def references(text, sources):
    known = {str(key) for key in sources}
    cited = list(dict.fromkeys(str(int(value)) for value in re.findall(r"\[(\d+)\]", text)))
    return {"resolved": [value for value in cited if value in known],
            "unknown": [value for value in cited if value not in known]}
