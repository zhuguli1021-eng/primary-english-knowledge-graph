"""人教英语教材目录与考点、CPP 目标的关联。"""
from collections import Counter


def validate(catalog, topics, cpp):
    errors = []
    topics_by_id = {t['id']: t for t in topics}
    domains = {'@' + t['domain'] for t in topics}
    details, cpp_refs = catalog['details'], catalog['cppRefs']
    valid_targets = set(topics_by_id) | set(details) | set(cpp_refs)
    if len(valid_targets) != len(topics) + len(details) + len(cpp_refs):
        errors.append('教材细目、原考点或 CPP 目标编号冲突')
    for key, item in {**details, **cpp_refs}.items():
        parents = item['parents']
        if not parents or set(parents) - domains - topics_by_id.keys():
            errors.append(f'{key} 的上级领域或考点无效')
    units = {u['id']: u for u in cpp['units']}
    seen_cpp = set()
    for key, ref in cpp_refs.items():
        ids = [ref['unit'], *ref.get('alsoUnits', [])]
        for uid in ids:
            block = units.get(uid, {}).get(ref['field'])
            if not block:
                errors.append(f'{key} 找不到 CPP 目标 {uid}')
            elif ref['field'] == 'grammar':
                if not ref.get('items') or set(ref['items']) - {g['name'] for g in block}:
                    errors.append(f'{key} 对应的 CPP 语法条目不存在')
        signature = (ref['unit'], ref['field'], tuple(sorted(ref.get('items', []))))
        if signature in seen_cpp:
            errors.append(f'{key} 重复引用同一 CPP 目标')
        seen_cpp.add(signature)
    sources = Counter()
    used = set()
    groups = set()
    for unit in catalog['units']:
        group = (unit['grade'], unit['semester'], unit['unit'])
        if group in groups or not unit['placements'] or unit['semester'] not in ('上', '下'):
            errors.append(f'教材目录无效或重复 {group}')
        groups.add(group)
        for row in unit['placements']:
            sources[row['sourceId']] += 1
            links = row['targets']
            if not row['objective'] or not links or len(set(links)) != len(links) or set(links) - valid_targets:
                errors.append(f"{row['sourceId']} 的教学目标或关联无效")
            used.update(links)
    if len(sources) != catalog['source']['expectedCount'] or any(n != 1 for n in sources.values()):
        errors.append('教材来源条目数不符或有重复')
    if (details.keys() | cpp_refs.keys()) - used:
        errors.append('存在未挂到教材的细目或 CPP 引用')
    return errors


def select(catalog, grade=None, semester=None, unit=None, q=None, topic=None):
    """返回筛选后的单元条目，以及解析这些条目所需的细目与 CPP 引用。"""
    grade = int(grade) if grade not in ('', None) else None
    if grade is not None and grade not in range(3, 10):
        raise ValueError('教材年级为 3 至 9')
    if semester and semester not in ('上', '下'):
        raise ValueError('册次写上或下')
    definitions = {**catalog['details'], **catalog['cppRefs']}
    query = (q or '').casefold()
    result, used = [], set()
    for book_unit in catalog['units']:
        if grade and book_unit['grade'] != grade or semester and book_unit['semester'] != semester:
            continue
        if unit and unit not in book_unit['unit']:
            continue
        rows = []
        for row in book_unit['placements']:
            keys = set(row['targets'])
            for key in row['targets']:
                keys.update(definitions.get(key, {}).get('parents', []))
            if topic and topic not in keys:
                continue
            terms = [row['name'], row['sourceId'], row['objective'], book_unit['unit'], *row.get('words', []), *keys]
            if query and not any(query in term.casefold() for term in terms):
                continue
            rows.append(row)
            used.update(row['targets'])
        if rows:
            result.append({**book_unit, 'placements': rows})
    return {'count': sum(len(u['placements']) for u in result), 'units': result,
            'details': {k: v for k, v in catalog['details'].items() if k in used},
            'cppRefs': {k: v for k, v in catalog['cppRefs'].items() if k in used},
            'source': catalog['source']}
