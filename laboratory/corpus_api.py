"""GET-only corpus routes; no import, extraction, approval or network side effects."""
import re
from urllib.parse import parse_qs, urlsplit


def handle_get(handler, path):
    if not path.startswith('/api/corpus'):
        return False
    corpus = handler.app.corpus
    if path == '/api/corpus':
        handler.send(corpus.overview())
        return True
    query = parse_qs(urlsplit(handler.path).query)

    def one(name, default=None):
        values = query.get(name, [default])
        if len(values) != 1:
            raise ValueError('Неоднозначный фильтр корпуса.')
        return values[0]

    topic = re.fullmatch(r'/api/corpus/topics/(-?\d{1,4})', path)
    paper = re.fullmatch(r'/api/corpus/papers/(20\d{2}\.emnlp-main\.\d+)', path)
    if topic:
        if set(query) - {'year', 'cohort', 'offset', 'limit'}:
            raise ValueError('Неизвестный фильтр корпуса.')
        year = one('year')
        handler.send(corpus.topic(int(topic[1]), int(year) if year is not None else None,
                                 one('cohort', 'numerator'), int(one('offset', '0')), int(one('limit', '20'))))
    elif paper:
        if query:
            raise ValueError('Для статьи дополнительные фильтры не предусмотрены.')
        handler.send(corpus.paper(paper[1]))
    else:
        handler.send({'error': 'Раздел корпуса не найден.'}, 404)
    return True
