"""
Debug script: Run a SINGLE Layer 3 case and dump the full pipeline state.
Usage: python tests/rag_quality/debug_layer3_single.py
"""
import asyncio
import json
import os
import sys
from unittest import mock

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

# Import from the Layer 3 script
from tests.rag_quality.run_layer3_e2e import (
    _TEST_EVIDENCE_REGISTRY,
    _injected_execute_plan_stub,
    _extract_answer_from_state,
    _extract_nodes_visited,
    CASE_TICKER_MAP,
)


async def debug_single_case():
    """Run one case and dump artifacts."""
    # Load dataset
    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    case = dataset["cases"][0]  # First case
    case_id = case["id"]
    question = case["question"]
    contexts = case["mock_contexts"]
    doc_type = case["doc_type"]
    ticker = CASE_TICKER_MAP.get(case_id, "")
    thread_id = f"debug-layer3-{case_id}"

    print(f"=== Debug Layer 3: {case_id} ===")
    print(f"Question: {question}")
    print(f"Ticker: {ticker}")
    print(f"Contexts count: {len(contexts)}")
    print(f"LANGGRAPH_SYNTHESIZE_MODE = {os.getenv('LANGGRAPH_SYNTHESIZE_MODE', 'NOT SET')}")
    print(f"LANGGRAPH_PLANNER_MODE = {os.getenv('LANGGRAPH_PLANNER_MODE', 'NOT SET')}")
    print()

    # Register test evidence
    _TEST_EVIDENCE_REGISTRY[thread_id] = {
        "contexts": contexts,
        "doc_type": doc_type,
        "case_id": case_id,
    }

    try:
        with mock.patch(
            "backend.graph.nodes.execute_plan_stub.execute_plan_stub",
            side_effect=_injected_execute_plan_stub,
        ):
            from backend.graph.runner import GraphRunner
            runner = GraphRunner.create()

            # Inject active_symbol via ui_context
            ui_ctx = {"active_symbol": ticker} if ticker else {}

            print(f">>> Running pipeline with ui_context={ui_ctx}...")
            final_state = await runner.ainvoke(
                thread_id=thread_id,
                query=question,
                output_mode="brief",
                ui_context=ui_ctx,
                confirmation_mode="skip",
            )

        # Dump key state fields
        print("\n=== FINAL STATE KEYS ===")
        if isinstance(final_state, dict):
            for k in sorted(final_state.keys()):
                v = final_state[k]
                if isinstance(v, str):
                    print(f"  {k}: (str, len={len(v)}) {v[:200]!r}")
                elif isinstance(v, dict):
                    print(f"  {k}: (dict, keys={list(v.keys())[:10]})")
                elif isinstance(v, list):
                    print(f"  {k}: (list, len={len(v)})")
                else:
                    print(f"  {k}: ({type(v).__name__}) {str(v)[:100]}")

        # Dump artifacts in detail
        artifacts = final_state.get("artifacts") or {} if isinstance(final_state, dict) else {}
        print("\n=== ARTIFACTS ===")
        for k, v in artifacts.items():
            if isinstance(v, str):
                print(f"  {k}: (str, len={len(v)})")
                print(f"    >>> {v[:500]!r}")
            elif isinstance(v, dict):
                print(f"  {k}: (dict, keys={list(v.keys())[:15]})")
                for sk, sv in list(v.items())[:5]:
                    print(f"    {sk}: {str(sv)[:200]!r}")
            elif isinstance(v, list):
                print(f"  {k}: (list, len={len(v)})")
                for i, item in enumerate(v[:3]):
                    print(f"    [{i}]: {str(item)[:200]!r}")
            else:
                print(f"  {k}: {str(v)[:200]!r}")

        # Extract answer
        answer, synth_mode = _extract_answer_from_state(final_state)
        nodes = _extract_nodes_visited(final_state)
        print(f"\n=== EXTRACTED ===")
        print(f"  synth_mode: {synth_mode}")
        print(f"  answer_len: {len(answer)}")
        print(f"  nodes_visited: {nodes}")
        print(f"  answer text:\n---\n{answer[:1000]}\n---")

        # Trace info
        trace = final_state.get("trace") or {} if isinstance(final_state, dict) else {}
        print(f"\n=== TRACE ===")
        for k, v in trace.items():
            print(f"  {k}: {str(v)[:300]}")

        # Clarify info
        clarify = final_state.get("clarify") or {} if isinstance(final_state, dict) else {}
        print(f"\n=== CLARIFY ===")
        print(f"  {clarify}")

    finally:
        _TEST_EVIDENCE_REGISTRY.pop(thread_id, None)


if __name__ == "__main__":
    asyncio.run(debug_single_case())
