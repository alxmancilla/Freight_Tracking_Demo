"""DEMO 4 - Vector Search + RAG with MongoDB Voyage AI embeddings.

The "GenAI logistics copilot" answers an operator's natural-language question by
retrieving the most relevant agent-memory documents (SOPs, lane history, playbooks)
and presenting them as grounded context. Filtering by topic shows pre-filter
push-down keeping recall scoped.

Run: python -m demos.demo4_vector_rag
"""
from db import get_db, embed_query
import config
from demos._presenter import banner, note, pause


def vector_search(db, query_text: str, k: int = 5, topic: str | None = None) -> list[dict]:
    qvec = embed_query(query_text)
    stage = {
        "$vectorSearch": {
            "index": config.IDX_AGENT_VECTOR,
            "path": "embedding",
            "queryVector": qvec,
            "numCandidates": max(100, k * 20),
            "limit": k,
        }
    }
    if topic:
        stage["$vectorSearch"]["filter"] = {"metadata.topic": {"$eq": topic}}

    pipeline = [
        stage,
        {"$project": {
            "_id": 1, "content": 1, "metadata": 1,
            "score": {"$meta": "vectorSearchScore"},
        }},
    ]
    return list(db[config.COL_AGENT_MEMORY].aggregate(pipeline))


def render_rag_prompt(question: str, hits: list[dict]) -> str:
    ctx_blocks = []
    for i, h in enumerate(hits, 1):
        ctx_blocks.append(f"[{i}] (topic={h['metadata']['topic']}, score={h['score']:.3f})\n{h['content']}")
    context = "\n\n".join(ctx_blocks)
    return (
        "You are a freight operations copilot. Use ONLY the context below to answer.\n"
        f"If the context is insufficient, say so.\n\n--- CONTEXT ---\n{context}\n\n"
        f"--- QUESTION ---\n{question}\n"
    )


def main() -> None:
    db = get_db()

    banner("DEMO 4 - Vector Search powered RAG")
    note(
        "Embeddings generated with Voyage AI ('voyage-4', 1024 dims) at ingest time.\n"
        "MongoDB acquired Voyage AI - these models are now the recommended default for\n"
        "Atlas Vector Search and run in the same SOC2/HIPAA boundary as your data.\n"
        "No second database, no separate vector store, no replication pipeline."
    )

    questions = [
        ("How should we handle a reefer load with a temperature deviation?", None),
        ("What is the standard procedure for a customs hold at a US port?", "exception_playbook"),
        ("Tell me about backhaul opportunities on West Coast lanes.",       "lane_history"),
    ]

    for q, topic in questions:
        pause(f"ENTER to run question: '{q}'" + (f"  [filter topic={topic}]" if topic else ""))
        hits = vector_search(db, q, k=4, topic=topic)
        print("\nTop matches:")
        for h in hits:
            print(f"  [{h['score']:.3f}] ({h['metadata']['topic']}) {h['content'][:110]}...")

        print("\n--- Prompt that would be sent to the LLM ---")
        print(render_rag_prompt(q, hits))

    banner("Why this matters for the GenAI platform")
    note(
        "1. Single-store: the copilot's memory lives next to the shipment data it\n"
        "   reasons about - join vector hits with live operational state in one query.\n"
        "2. Pre-filtering: $vectorSearch.filter pushes down to the HNSW graph, so a\n"
        "   topic constraint does not destroy recall the way post-filtering would.\n"
        "3. Voyage models: best-in-class retrieval quality, billed through MongoDB,\n"
        "   already covered by your Atlas DPA - zero extra vendor onboarding."
    )


if __name__ == "__main__":
    main()
