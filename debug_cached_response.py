"""Debug script: 模拟完整 strip pipeline 看 cache response 到底为什么 parse fail。"""
from diskcache import Cache
import json
import re
import sys

sys.path.insert(0, '.')
from services._text_utils import strip_thinking

c = Cache('data/llm_cache')
for key in c.iterkeys():
    v = c.get(key)
    if v is None or not isinstance(v, dict):
        continue
    content = v.get('content', '') or ''
    if 'AI 产品' in content or 'rewrite' in content or '字节' in content:
        print(f'=== KEY: {key} ===')
        print(f'CONTENT LEN: {len(content)}')
        print(f'first 100: {content[:100]!r}')
        break

# 模拟 strip_thinking
stripped = strip_thinking(content)
print(f'after strip_thinking len: {len(stripped)}')
print(f'first 100: {stripped[:100]!r}')

# 模拟 _strip_code_fence（按 services/resume_rewriter.py:73-86）
text = stripped.strip()
if text.startswith('```'):
    lines = text.split('\n')
    if lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    text = '\n'.join(lines)
text = text.strip()
print(f'after strip_code_fence len: {len(text)}')
print(f'first 100: {text[:100]!r}')

# 模拟 _safe_json_loads（按 services/resume_rewriter.py:256-274）
try:
    parsed = json.loads(text)
    print('DIRECT JSON PARSE OK')
except json.JSONDecodeError as e:
    print(f'DIRECT JSON PARSE FAIL at pos {e.pos}: {e}')
    print(f'around error: {text[max(0,e.pos-100):e.pos+100]!r}')

# 尝试抽取 {...}
m = re.search(r'\{[\s\S]*\}', text)
if m:
    try:
        parsed = json.loads(m.group(0))
        print('REGEX JSON PARSE OK')
        print('keys:', list(parsed.keys()))
        rewrites = parsed.get('rewrites', [])
        print('rewrites count:', len(rewrites))
        for i, r in enumerate(rewrites):
            txt = r.get('rewritten', '')
            print(f'  [{i}] contains 200: {"200" in txt}, 120: {"120" in txt}, 18: {"18" in txt}')
    except json.JSONDecodeError as e:
        print(f'REGEX JSON PARSE FAIL at pos {e.pos}: {e}')
        print(f'around error: {m.group(0)[max(0,e.pos-100):e.pos+100]!r}')
else:
    print('NO {...} BLOCK FOUND')
