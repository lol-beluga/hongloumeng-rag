"""Small, read-only tool surface. The model cannot execute code or choose file paths."""
import re


def string(maximum=400, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def array(items, low=0, high=8):
    return {"type": "array", "items": items, "minItems": low, "maxItems": high}


def obj(properties, required):
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def tool(name, description, parameters):
    return {"type": "function", "function": {"name": name, "description": description,
                                               "parameters": parameters}}


CITATION = obj({"evidence_id": string(80), "quote": string(160, 8)}, ["evidence_id", "quote"])
CLAIM = obj({"statement": string(300, 2), "kind": {"type": "string", "enum": ["fact", "interpretation"]},
             "citations": array(CITATION, 1, 2)}, ["statement", "kind", "citations"])
TOOLS = [
    tool("plan_research", "复杂问题先列出需要查证的子问题，最多5项。", obj(
        {"questions": array(string(200), 1, 5)}, ["questions"])),
    tool("search_text", "检索原著片段。可换关键词或限定章节；相似度不是答案置信度。", obj(
        {"query": string(300), "top_k": integer(1, 5), "chapter_start": integer(1, 120),
         "chapter_end": integer(1, 120)}, ["query"])),
    tool("read_passage", "读取已知原文编号及前后相邻片段，以核对上下文。", obj(
        {"evidence_id": string(80), "neighbors": integer(0, 2)}, ["evidence_id"])),
    tool("list_chapters", "按回数范围查看目录，返回首个片段编号；支持分页。", obj(
        {"chapter_start": integer(1, 120), "chapter_end": integer(1, 120),
         "offset": integer(0, 200), "limit": integer(1, 20)}, [])),
    tool("submit_answer", "提交最终结论，最多4项。每项结论引用本任务已获取的原文，quote连续逐字摘录，建议8至80字。"
         "区分事实与解读；证据不足时claims留空并在limitations说明，不得编造引用。", obj(
        {"claims": array(CLAIM, 0, 4), "limitations": array(string(400), 0, 4)}, ["claims", "limitations"]))
]
SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


def validate(schema, value, path="arguments"):
    """Validate the deliberately small JSON Schema subset used above, including bool/int distinction."""
    kind = schema["type"]
    expected = {"string": str, "integer": int, "array": list, "object": dict}[kind]
    if type(value) is not expected:
        raise ValueError(f"{path} 必须是 {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} 不在允许值中")
    if kind == "string" and not schema.get("minLength", 0) <= len(value.strip()) <= schema.get("maxLength", 10000):
        raise ValueError(f"{path} 长度不合法")
    if kind == "integer" and not schema["minimum"] <= value <= schema["maximum"]:
        raise ValueError(f"{path} 超出范围")
    if kind == "array":
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"{path} 数量不合法")
        for i, item in enumerate(value):
            validate(schema["items"], item, f"{path}[{i}]")
    if kind == "object":
        if set(value) - set(schema["properties"]) or set(schema["required"]) - set(value):
            raise ValueError(f"{path} 存在未知字段或缺少必填字段")
        for key, item in value.items():
            validate(schema["properties"][key], item, f"{path}.{key}")


def validate_report(report, evidence):
    validate(SCHEMAS["submit_answer"], report)
    if not report["claims"] and not report["limitations"]:
        raise ValueError("没有结论时必须说明证据不足之处。")
    for claim in report["claims"]:
        for citation in claim["citations"]:
            chunk = evidence.get(citation["evidence_id"])
            if not chunk:
                raise ValueError("引用了本任务尚未读取的原文编号。")
            normalize = lambda text: re.sub(r"\s+", "", text)
            if normalize(citation["quote"]) not in normalize(chunk["content"]):
                raise ValueError(f"引用文字不在原文{citation['evidence_id']}中，请从该片段重新摘录；不能用省略号拼接。")
    return report


def render_report(report, evidence):
    lines = []
    for i, claim in enumerate(report["claims"], 1):
        label = "事实" if claim["kind"] == "fact" else "解读"
        lines.append(f"{i}. 【{label}】{claim['statement']}")
        for citation in claim["citations"]:
            chunk = evidence[citation["evidence_id"]]
            lines.append(f"\n> {citation['quote']}\n\n来源：{chunk['source']} [{citation['evidence_id']}]\n")
    if report["limitations"]:
        lines.append("证据范围与不足：\n" + "\n".join(f"- {s}" for s in report["limitations"]))
    return "\n".join(lines)
