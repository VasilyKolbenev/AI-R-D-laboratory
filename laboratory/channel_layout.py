"""Whole-paragraph projection for a bounded channel post."""
from copy import deepcopy

VERSION = 'whole-findings-v1'


def fit(data, render, limit):
    """Keep required findings and greedily retain other complete paragraphs."""
    if not isinstance(data, dict) or not callable(render) or type(limit) is not int or limit < 1:
        return None
    story = data.get('story')
    if not isinstance(story, list) or any(not isinstance(section, dict) for section in story):
        return None
    sections = [index for index, section in enumerate(story) if section.get('id') == 'findings']
    if len(sections) != 1:
        return None
    section_index = sections[0]
    findings = story[section_index].get('items')
    if not isinstance(findings, list) or not findings or any(
            not isinstance(item, str) or not item.strip() for item in findings):
        return None
    mandatory = [index for index, text in enumerate(findings)
                 if index == 0 or any(character.isdigit() for character in text)]

    def candidate(indices):
        projection = deepcopy(data)
        projection['story'][section_index]['items'] = [findings[index] for index in indices]
        try:
            text = render(projection)
            units = len(text.encode('utf-16-le')) // 2 if isinstance(text, str) else limit + 1
        except (TypeError, ValueError, KeyError):
            return None
        if projection.get('post_compacted') is not False or units > limit:
            return None
        return text, units

    selected = list(mandatory)
    result = candidate(selected)
    if result is None:
        return None
    for index in range(len(findings)):
        if index in mandatory:
            continue
        proposed = sorted([*selected, index])
        rendered = candidate(proposed)
        if rendered is not None:
            selected, result = proposed, rendered
    return {'text': result[0], 'metadata': {
        'version': VERSION, 'selected_findings': selected,
        'omitted_findings': [index for index in range(len(findings)) if index not in selected],
        'mandatory_findings': mandatory, 'utf16_units': result[1], 'limit': limit}}
