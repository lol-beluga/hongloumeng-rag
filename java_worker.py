"""One job per subprocess. JSON stdin/stdout; credentials stay on the server.

The Java task ID is also the Python checkpoint ID, so explicit retries resume
an existing research run. Lookup mode never calls a model API.
"""
import json
import sys
import uuid


def execute(request):
    from agent_harness import ResearchAgent, public_result
    from rag_system import PROJECT_DIR, RagSystem, load_api_key
    from run_store import RunStore

    job_id = request['id']
    if uuid.UUID(job_id).hex != job_id:
        raise ValueError('invalid job ID')
    question = request['question'].strip()
    if not 1 <= len(question) <= 2000:
        raise ValueError('invalid question')
    mode = request['mode']
    if mode not in ('lookup', 'research'):
        raise ValueError('invalid mode')
    rag = RagSystem(load_api_key(required=False) or None) if mode == 'research' else RagSystem()
    rag.initialize()
    if mode == 'lookup':
        sources = rag.search_chunks(question, top_k=5)
        return {'run_id': job_id, 'status': 'completed', 'answer': '',
                'sources': sources, 'mode': 'lookup'}
    store = RunStore(PROJECT_DIR / 'runs' / 'research.sqlite3')
    agent = ResearchAgent(rag, store)
    try:
        state = store.load(job_id)
    except ValueError:
        state = agent.start(question, run_id=job_id)
    else:
        if state['question'] != question:
            raise ValueError('checkpoint question mismatch')
        state = agent.resume(job_id, extend_budget=request.get('extend_budget') is True)
    return public_result(state)


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        request = json.loads(sys.stdin.read(20000))
        result = execute(request)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # Raw exceptions may contain request headers or provider details.
        print(json.dumps({'error': type(exc).__name__}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
