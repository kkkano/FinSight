# Chat Latency Budget Probe (2026-05-04)

## Profiles

### stub

```env
LANGGRAPH_PLANNER_MODE=stub
CHAT_UX_REVIEW_THRESHOLD_MS=20000
```

### llm-chat-45s

```env
LANGGRAPH_PLANNER_MODE=llm
LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC=45
LANGGRAPH_PLANNER_CHAT_MAX_TOKENS=1800
LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS=2
LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC=45
CHAT_UX_REVIEW_THRESHOLD_MS=60000
```

### llm-chat-75s

```env
LANGGRAPH_PLANNER_MODE=llm
LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC=75
LANGGRAPH_PLANNER_CHAT_MAX_TOKENS=2200
LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS=2
LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC=75
CHAT_UX_REVIEW_THRESHOLD_MS=90000
```

## Summary

| Profile | avg ms | p95-ish ms | max ms | reviews |
|---|---:|---:|---:|---:|
| stub | 137 | 218 | 218 | 0 |
| llm-chat-45s | 126 | 150 | 150 | 0 |
| llm-chat-75s | 148 | 235 | 235 | 0 |

## Cases

| Profile | ID | Label | ms | Planner | Hits |
|---|---|---|---:|---|---|
| stub | L01 | smalltalk | 147 | None/None | - |
| stub | L02 | oos | 127 | None/None | - |
| stub | L03 | concept | 115 | None/None | - |
| stub | L04 | quote | 127 | None/None | - |
| stub | L05 | news | 119 | None/None | - |
| stub | L06 | mixed | 125 | None/None | - |
| stub | L07 | macro | 218 | None/None | - |
| stub | L08 | deixis | 118 | None/None | - |
| llm-chat-45s | L01 | smalltalk | 119 | None/None | - |
| llm-chat-45s | L02 | oos | 134 | None/None | - |
| llm-chat-45s | L03 | concept | 150 | None/None | - |
| llm-chat-45s | L04 | quote | 123 | None/None | - |
| llm-chat-45s | L05 | news | 121 | None/None | - |
| llm-chat-45s | L06 | mixed | 122 | None/None | - |
| llm-chat-45s | L07 | macro | 122 | None/None | - |
| llm-chat-45s | L08 | deixis | 120 | None/None | - |
| llm-chat-75s | L01 | smalltalk | 123 | None/None | - |
| llm-chat-75s | L02 | oos | 122 | None/None | - |
| llm-chat-75s | L03 | concept | 221 | None/None | - |
| llm-chat-75s | L04 | quote | 235 | None/None | - |
| llm-chat-75s | L05 | news | 118 | None/None | - |
| llm-chat-75s | L06 | mixed | 121 | None/None | - |
| llm-chat-75s | L07 | macro | 120 | None/None | - |
| llm-chat-75s | L08 | deixis | 125 | None/None | - |

## Full Answers

### stub / L01 / smalltalk

Elapsed: `147ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L02 / oos

Elapsed: `127ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L03 / concept

Elapsed: `115ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L04 / quote

Elapsed: `127ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L05 / news

Elapsed: `119ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L06 / mixed

Elapsed: `125ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L07 / macro

Elapsed: `218ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### stub / L08 / deixis

Elapsed: `118ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L01 / smalltalk

Elapsed: `119ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L02 / oos

Elapsed: `134ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L03 / concept

Elapsed: `150ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L04 / quote

Elapsed: `123ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L05 / news

Elapsed: `121ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L06 / mixed

Elapsed: `122ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L07 / macro

Elapsed: `122ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-45s / L08 / deixis

Elapsed: `120ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L01 / smalltalk

Elapsed: `123ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L02 / oos

Elapsed: `122ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L03 / concept

Elapsed: `221ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L04 / quote

Elapsed: `235ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L05 / news

Elapsed: `118ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L06 / mixed

Elapsed: `121ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L07 / macro

Elapsed: `120ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---

### llm-chat-75s / L08 / deixis

Elapsed: `125ms`

```json
{}
```

---
{"detail":"session_id format invalid, expected tenant:user:thread"}
---
