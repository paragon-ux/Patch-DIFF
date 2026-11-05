"""Independently reconcile a captured benchmark without changing its packet or database."""

import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

PACKET = Path(sys.argv[1]).resolve()
OUTPUT = Path(sys.argv[2]).resolve()
sys.dont_write_bytecode = True
sys.path.insert(0, str(PACKET / 'inputs/primary/evaluator'))
from full_byte_oracle import SOURCE_HASHES, expected
from verify_hard_suite import check_workspace
from app.pdcp.observed_batch import BatchScope, apply_observed_batch, parse_batch_request, BATCH_PROTOCOL_VERSION
from app.core.result import AcceptedCoreResult


def load(path):
    return json.loads(path.read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stamp_ns(row):
    return int(datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')).timestamp() * 1e9)


def body(result):
    return result.get('structuredContent') or json.loads(result['content'][0]['text'])


def wire_calls(trial):
    calls, catalogs = [], []
    for path in sorted(trial.glob('wire-*.jsonl')):
        pending = {}
        for row in [json.loads(line) for line in path.read_text().splitlines() if line]:
            message = row['message']
            if row['direction'] == 'request':
                if 'id' in message:
                    assert message['id'] not in pending
                    pending[message['id']] = row
                continue
            request = pending.pop(message.get('id'), None)
            if request is None:
                continue
            method = request['message']['method']
            if method == 'tools/list':
                catalogs.append(sorted(t['name'] for t in message['result']['tools']))
            if method == 'tools/call':
                params = request['message']['params']
                assert not message.get('error') and not message['result'].get('isError'), (path, params['name'])
                calls.append({'name': params['name'], 'args': params.get('arguments', {}),
                              'body': body(message['result']), 'start': request, 'end': row})
        assert not any(r['message']['method'] == 'tools/call' for r in pending.values()), path
    return sorted(calls, key=lambda c: c['start']['ns']), catalogs


reference = expected()
schedule = load(PACKET / 'operator/schedule.json')
assert len(schedule) == 18
counts = collections.Counter((r['arm'], r['environment']) for r in schedule)
assert len(counts) == 6 and set(counts.values()) == {3}
summary = load(PACKET / 'results/results.json')
reported = {r['id']: r for r in summary['results']}
read_tools = {'patchdiff_read_target', 'patchdiff_find_occurrences'}
structural_tools = read_tools | {'patchdiff_list_scopes', 'patchdiff_observe_scopes', 'patchdiff_commit_bundle'}
workspace_tools = structural_tools | {'patchdiff_initialize_target', 'patchdiff_save'}
files_checked, behavior_checks, commits_checked, scopes_checked = 0, 0, 0, 0
verified = []

for assignment in schedule:
    trial = PACKET / 'runs' / assignment['id']
    receipt = load(trial / 'result.json')
    assert all(receipt[k] == v for k, v in assignment.items())
    assert receipt == reported[assignment['id']]
    assert receipt['outcome'] == 'success'
    start = load(trial / 'start.json')
    assert start['boot'] == receipt['end']['boot']
    elapsed = (receipt['end']['ns'] - start['ns']) / 1e9
    assert abs(elapsed - receipt['e2e_seconds']) < 1e-8 and elapsed <= 600
    assert (trial/'prompt.md').read_bytes().endswith((PACKET/'inputs/primary/prompts/TASK.md').read_bytes())
    for folder in ('workspace', 'verification-files'):
        directory = trial / folder
        inventory = {p.name for p in directory.iterdir()} - ({'.git'} if assignment['environment'] == 'git' else set())
        assert inventory == set(SOURCE_HASHES), (trial, folder, inventory)
        for filename, data in reference.items():
            path = directory / filename
            assert path.is_file() and not path.is_symlink() and path.read_bytes() == data, (trial, folder, filename)
            if folder == 'workspace': files_checked += 1
    behavior = check_workspace(trial / 'verification-files', 'audit_' + assignment['id'])
    assert behavior['total'] == 20 and behavior['passed'] == 20, trial
    behavior_checks += 20
    transcript_bytes = (trial/'antigravity.jsonl').read_bytes()
    assert digest(transcript_bytes) == receipt['editor']['transcript_sha256']
    transcript = [json.loads(line) for line in transcript_bytes.splitlines() if line]
    plans = [r for r in transcript if r.get('type') == 'PLANNER_RESPONSE']
    tools = [tool for row in plans for tool in row.get('tool_calls', [])]
    tool_counts = dict(collections.Counter(tool['name'] for tool in tools))
    assert len(plans) == receipt['editor']['steps'] and len(tools) == receipt['editor']['calls']
    assert tool_counts == receipt['editor']['tool_counts']
    interval = (stamp_ns(transcript[-1]) - stamp_ns(plans[0])) / 1e9
    assert interval == receipt['editor']['recorded_editor_interval_seconds']
    errors = sum(row.get('status') == 'ERROR' for row in transcript)
    assert errors == receipt['editor']['errors'] == 0
    tokens = {key: sum(r.get(key, 0) for r in plans) for key in ('input_tokens', 'cache_read_tokens', 'output_tokens')}
    assert tokens == receipt['editor']['tokens']
    calls, catalogs = wire_calls(trial)
    calls = [c for c in calls if c['start']['ns'] >= start['ns']]
    assert len(calls) == receipt['mcp_calls']
    assert round(sum((c['end']['ns']-c['start']['ns'])/1e9 for c in calls), 8) == round(receipt['mcp_elapsed_seconds'], 8)
    captured = load(trial/'editor-rpc.json')
    assert not captured['unresolved'] and len(captured['calls']) == len(calls)
    host = [json.loads(line) for line in (trial/'host-rpc.jsonl').read_text().splitlines()] if (trial/'host-rpc.jsonl').exists() else []
    host_calls = [r for r in host if r['request']['method'] == 'tools/call']
    assert dict(collections.Counter(r['request']['params']['name'] for r in host_calls)) == receipt['host_calls']
    if assignment['arm'] == 'native':
        assert not calls and not catalogs and not host_calls
        assert not any(name.startswith('mcp_') for name in tool_counts)
    else:
        allowed = workspace_tools if assignment['arm'] == 'workspace' else structural_tools
        assert catalogs and all(set(c) == allowed for c in catalogs)
        assert set(c['name'] for c in calls) <= allowed
        assert not set(tool_counts) & {'run_command','edit_file','write_file','write_to_file','replace_file_content','multi_replace_file_content'}
        target_map = {}
        for row in host_calls:
            if row['request']['params']['name'] == 'patchdiff_initialize_target':
                payload = body(row['response']['result'])
                target_map[payload['target_file_id']] = row['request']['params']['arguments']['filename']
        versions, buffers, observations = {}, {}, {}
        for call in calls:
            args, result = call['args'], call['body']
            if call['name'] == 'patchdiff_initialize_target':
                assert args['from_workspace'] is True and result['status'] == 'ok'
                target_map[result['target_file_id']] = args['filename']
            if call['name'] == 'patchdiff_observe_scopes':
                snapshot = result['snapshot']
                tid = snapshot['target_file_id']
                filename = target_map[tid]
                content = buffers.setdefault(tid, (PACKET/'inputs/primary/fixtures'/filename).read_bytes().decode().replace('\r\n','\n').replace('\r','\n'))
                assert snapshot['expected_current_hash'] == digest(content.encode())
                assert snapshot['expected_target_version'] == versions.setdefault(tid, 0)
                for scope in result['scopes']:
                    sliced = content[scope['scope_start']:scope['scope_end']]
                    assert digest(sliced.encode()) == scope['observed_scope_hash']
                observations[snapshot['observation_bundle_id']] = result
            if call['name'] == 'patchdiff_commit_bundle':
                snapshot = args['snapshot']
                tid = snapshot['target_file_id']
                obs = observations[snapshot['observation_bundle_id']]
                assert obs['snapshot'] == snapshot
                assert snapshot['expected_current_hash'] == digest(buffers[tid].encode())
                record = {'format': BATCH_PROTOCOL_VERSION, **snapshot, 'intent': args['intent'], 'groups': args['groups']}
                groups = parse_batch_request(record)
                by_id = {s['observation_id']: s for s in obs['scopes']}
                scopes = tuple(BatchScope(g.observation_id, by_id[g.observation_id]['ordinal'],
                               by_id[g.observation_id]['scope_start'], by_id[g.observation_id]['scope_end'],
                               by_id[g.observation_id]['observed_scope_hash']) for g in groups)
                applied = apply_observed_batch(buffers[tid], groups, scopes, target_type='text/plain')
                assert isinstance(applied, AcceptedCoreResult), (trial, result)
                assert applied.after_hash == result['transaction']['after']['hash']
                assert applied.before_hash == result['transaction']['before']['hash']
                buffers[tid] = applied.target_content
                versions[tid] += 1
                assert versions[tid] == result['transaction']['after']['version']
                commits_checked += 1
                scopes_checked += len(scopes)
        assert len(target_map) == len(buffers) == 5
        for tid, filename in target_map.items():
            assert buffers[tid].encode() == reference[filename]
        if assignment['arm'] == 'workspace':
            saves = [c for c in calls if c['name'] == 'patchdiff_save']
            assert len(saves) == 5 and len(load(trial/'publication-verification.json')) == 5
            for save in saves:
                result, args = save['body'], save['args']
                assert args['sync_workspace'] is True and result['status'] == 'saved'
                sync = result['workspace_sync']
                assert sync['publication'] == 'installed' and sync['durability'] == 'confirmed'
                assert sync['disk_sha256'] == digest(reference[sync['synced_path']])
                assert result['current_hash'] == digest(buffers[args['target_file_id']].encode())
                assert args['expected_target_version'] == result['version']
        else:
            assert len(host_calls) == 20
            assert len([r for r in host_calls if r['request']['params']['name']=='patchdiff_replay']) == 5
            for row in host_calls:
                if row['request']['params']['name']=='patchdiff_replay':
                    replay=body(row['response']['result'])
                    assert replay['status']=='success' and replay['materialized_state_matches']
            publications = [json.loads(line) for line in (trial/'publication.jsonl').read_text().splitlines()]
            assert len(publications)==5 and all(item['sha256']==digest(reference[item['file']]) for item in publications)
    prepared = load(trial/'prepared.json')
    setup_total = prepared['total_seconds']
    handoff = (start['ns'] - prepared['at']['ns']) / 1e9
    assert abs(handoff-receipt['connector_handoff_seconds']) < 1e-8
    publication_ns = None
    if assignment['arm'] == 'workspace':
        publication_ns = max(c['end']['utc_ns'] for c in saves)
    elif assignment['arm'] == 'structural':
        publication_ns = max(item['at']['utc_ns'] for item in publications)
    def iso(ns):
        return datetime.fromtimestamp(ns/1e9, timezone.utc).isoformat()
    verified.append({**assignment, 'outcome': receipt['outcome'], 'e2e_seconds': elapsed,
        'editor_seconds': interval, 'steps': len(plans), 'editor_calls': len(tools), 'mcp_calls': len(calls),
        'host_calls':len(host_calls), 'host_writes':receipt['host_file_writes'],
        'mcp_seconds':receipt['mcp_elapsed_seconds'], 'host_rpc_seconds':receipt['host_rpc_seconds'],
        'verification_seconds':receipt['verification_seconds'], 'prepare_seconds':setup_total,
        'git_setup_seconds':prepared['git_setup_seconds'], 'db_setup_seconds':prepared['db_create_migrate_seconds'],
        'connector_handoff_seconds':handoff,
        'prompt_handoff_seconds':receipt['prompt_handoff_seconds'], 'terminal_handoff_seconds':receipt['handoff_seconds'],
        'tokens':tokens,'tool_counts':tool_counts,'byte_exact_files':5,'behavior_checks':20,
        'transcript_sha256':digest(transcript_bytes),
        'start_utc':iso(start['utc_ns']),
        'submitted_utc':iso(load(trial/'submitted.json')['utc_ns']),
        'publication_utc':iso(publication_ns) if publication_ns is not None else None,
        'publication_observed_utc':iso(receipt['publication_observed']['utc_ns']),
        'verified_utc':iso(receipt['verified_at']['utc_ns']),
        'finished_utc':iso(receipt['end']['utc_ns'])})

cleanup = [load(path) for path in (PACKET/'runtime').glob('runner-*/cleanup.json')]
assert cleanup and all(row['status']=='CLEAN' for row in cleanup)
assert not (PACKET/'runtime/lease.json').exists()
wheel = next((PACKET/'packages').glob('*.whl'))
output = {'source_head':summary['head'],'wheel_sha256':digest(wheel.read_bytes()),
          'packet_manifest_sha256':digest((PACKET/'operator/packet-sha256.json').read_bytes()),
          'verification':{'trials':len(verified),'byte_exact_files':files_checked,'behavior_checks_passed':behavior_checks,
                          'reconstructed_guarded_commits':commits_checked,'reconstructed_scope_groups':scopes_checked,
                          'cleanup': 'CLEAN'},
          'limitations': ['Model/reasoning are operator attestations; provider confirmation is absent.',
                         'host_build is the placeholder production, not an exact Antigravity version.',
                         'PostgreSQL was torn down; stored publication checks are captured evidence, not a current database requery.'],
          'one_time_setup':summary['one_time_setup'],'trials':verified}
OUTPUT.write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output['verification']))
for env in ('git','nongit','pooled'):
 for arm in ('native','structural','workspace'):
  rows=[r for r in verified if r['arm']==arm and (env=='pooled' or r['environment']==env)]
  print(env,arm,'n',len(rows), 'e2e mean/median',round(statistics.mean(r['e2e_seconds'] for r in rows),3),round(statistics.median(r['e2e_seconds'] for r in rows),3),
        'steps',round(statistics.mean(r['steps'] for r in rows),2),'calls',round(statistics.mean(r['editor_calls'] for r in rows),2),
        'context',round(statistics.mean(r['tokens']['input_tokens']+r['tokens']['cache_read_tokens'] for r in rows)))
