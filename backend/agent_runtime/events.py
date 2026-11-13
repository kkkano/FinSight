"""schema v2 事件、原文消息块与检查点；不解释或改写模型正文。"""
from copy import deepcopy
from datetime import datetime, timezone
import inspect
import time
import uuid


class EventSink:
    def __init__(self, queue, *, run_id, session_id, message_id=None, initial_seq=0, checkpoint=None):
        self.queue, self.run_id, self.session_id = queue, run_id, session_id
        self.message_id = message_id or "assistant:" + run_id
        self.epoch, self.seq = uuid.uuid4().hex, initial_seq
        self.checkpoint, self.last_checkpoint = checkpoint, 0.0
        self.blocks, self.thinking, self.runtime = {}, [], None

    def envelope(self, kind, payload, agent_id="root"):
        self.seq += 1
        return {"schema_version": "2", "type": kind, "runtime_type": kind,
                "run_id": self.run_id, "session_id": self.session_id, "message_id": self.message_id,
                "attempt_id": self.epoch, "stream_epoch": self.epoch, "seq": self.seq,
                "event_id": self.epoch + ":" + str(self.seq), "agent_id": agent_id,
                "parent_agent_id": None if agent_id == "root" else "root",
                "timestamp": datetime.now(timezone.utc).isoformat(), "payload": payload}

    async def emit(self, kind, payload, agent_id="root"):
        outgoing = self.envelope(kind, payload, agent_id)
        if kind == "content.delta":
            outgoing.update(type="token", content=payload["delta"], block_id=payload["block_id"])
            block = self.blocks.setdefault(payload["block_id"], {"id": payload["block_id"], "kind": "text",
                "content": "", "revision": 0, "seq": self.seq, "agent_id": agent_id,
                "agent_label": payload.get("agent_label")})
            block["content"] += payload["delta"]
        elif kind == "content.block_finished" and payload["block_id"] in self.blocks:
            self.blocks[payload["block_id"]].update({key: payload[key] for key in
                ("content_phase", "finish_reason", "completion_status") if key in payload})
        elif kind == "content.revised":
            self.blocks[payload["block_id"]] = {"id": payload["block_id"], "kind": "text",
                "content": payload["text"], "revision": payload["revision"], "seq": self.seq,
                "agent_id": agent_id, "content_phase": "answer", "completion_status": "complete",
                "revision_of": list(payload["revision_of"]), "review_id": payload["review_id"]}
        elif kind in {"review.started", "review.finished"}:
            review_id = payload["review_id"]
            self.blocks[review_id] = {"id": review_id, "kind": "review", "review": deepcopy(payload),
                "revision": 1 if kind == "review.finished" else 0, "seq": self.seq, "agent_id": agent_id}
        elif kind in {"reasoning.delta", "reasoning.completed"}:
            block = self.blocks.setdefault(payload["block_id"], {"id": payload["block_id"], "kind": "reasoning",
                "content": "", "revision": 0, "seq": self.seq, "agent_id": agent_id,
                "agent_label": payload.get("agent_label"), "reasoning_kind": payload.get("kind", "provider_raw"),
                "provider": payload.get("provider")})
            block["content"] += payload.get("delta") or ""
            for key in ("duration_ms", "truncated"):
                if key in payload:
                    block[key] = payload[key]
        elif kind == "artifact.ready":
            artifact = payload["artifact"]
            self.blocks[artifact["artifact_id"]] = {"id": artifact["artifact_id"], "kind": "artifact",
                "artifact": deepcopy(artifact), "revision": 1, "seq": self.seq, "agent_id": agent_id}
        elif kind in {"action.proposed", "action.finished"}:
            action = payload["action"]
            self.blocks[action["action_id"]] = {"id": action["action_id"], "kind": "action", "action": deepcopy(action),
                                              "revision": 1, "seq": self.seq}
        if kind.startswith(("tool.", "agent.", "skill.", "activity.")):
            self.thinking.append({"stage": kind, "message": payload.get("summary") or payload.get("title") or "",
                "timestamp": outgoing["timestamp"], "eventType": "trace", "runId": self.run_id,
                "sessionId": self.session_id, "result": {**payload, "runtime_type": kind,
                    "seq": self.seq, "agent_id": agent_id, "run_id": self.run_id, "session_id": self.session_id}})
        await self.queue.put(outgoing)
        if self.checkpoint and time.monotonic() - self.last_checkpoint >= 1:
            self.last_checkpoint = time.monotonic()
            try:
                value = self.checkpoint(self.snapshot())
                if inspect.isawaitable(value):
                    await value
            except Exception:
                await self.queue.put(self.envelope("delivery.persistence_unconfirmed",
                    {"message": "生成内容暂未保存，正在保留当前页面结果。"}))

    def snapshot(self):
        revision = getattr(self.runtime, "report_revision", None)
        return {"attempt_id": self.epoch, "stream_epoch": self.epoch, "committed_seq": self.seq,
                "blocks": deepcopy(list(self.blocks.values())), "thinking": deepcopy(self.thinking),
                "response": revision["content"] if revision else self.runtime.root_content if self.runtime else "",
                "artifacts": deepcopy(self.runtime.data.artifacts) if self.runtime else []}
