"""TEST_ONLY review/story UI fixture. Never loads real bot credentials or a model."""
import argparse
from pathlib import Path
import threading

from laboratory.server import Handler, Laboratory, LocalServer


class FakeTelegram:
    def __init__(self,*args): self.deliveries=0
    def bind_workflow(self,*args): pass
    def status(self): return {'configured':True,'owner_id':123,'username':'TEST_ONLY','status':'TEST_ONLY fake transport'}
    def send_result(self,*args): self.deliveries+=1;return {'status':'sent','test_only':True}
    def stop(self): pass


class FixtureHandler(Handler):
    def do_GET(self):
        if self.path=='/__test__/stats':
            return self.send({'test_only':True,'provider_dispatches':0,'run_id':self.server.fixture_run,
                              'related_id':self.server.fixture_related,'deliveries':self.app.telegram.deliveries})
        return super().do_GET()
    def do_POST(self):
        if self.path=='/__test__/shutdown':
            self.send({'test_only':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        return super().do_POST()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-dir',type=Path,required=True);args=parser.parse_args()
    def forbidden(*unused): raise AssertionError('Real research forbidden in UI fixture')
    app=Laboratory(args.data_dir,runner=forbidden,telegram_factory=FakeTelegram)
    source,_=app.store.add_source('TEST_ONLY: стратегия поиска решений по сохранённой истории',title='TEST_ONLY Dream-RSI разбор')
    related=app.store.create_plan({'source_ids':[source['id']],'question':'TEST_ONLY: пустое вложение'})
    app.store.approve(related['id'],related['plan_hash'],True,'TEST_ONLY-related-review')
    app.store.finish(related['id'],{'status':'completed','text':'TEST_ONLY: данных недостаточно.',
        'usage':{'input_tokens':150,'cached_input_tokens':50,'output_tokens':25},'raw':{'dispatched':True,'test_only':True}})
    run=app.store.create_plan({'source_ids':[source['id']],'question':'TEST_ONLY: как использовать историю попыток при поиске оптимизации кода?'})
    app.store.approve(run['id'],run['plan_hash'],True,'TEST_ONLY-main-review')
    report='''## Краткий вывод
TEST_ONLY: экспериментальное описание стратегии replay, не настоящий научный результат.
## Механизм
Сначала сохраняется дерево; затем стратегии проходят известные ветви; новый запуск создаёт новые исходы.
## Доказательства
TEST_ONLY: авторские результаты ограничены конкретной конфигурацией.
<script>window.__reviewInjected=true</script>
## Источники
https://example.org/TEST_ONLY-source
<lab_memory_review>{"comparisons":[]}</lab_memory_review>'''
    app.store.finish(run['id'],{'status':'completed','text':report,'usage':{'input_tokens':1000,'cached_input_tokens':700,'output_tokens':100},'raw':{'dispatched':True,'test_only':True}})
    body=app.store.review.schema()['template']
    body['evidence']=[
        {'id':'e1','claim':'TEST_ONLY: механизм описан в отчёте','basis':'saved_report','locator':'Раздел «Механизм»','source_url':'https://example.org/TEST_ONLY-source','excerpt':'Сначала сохраняется дерево, затем проверяются стратегии.','limitations':'Это не независимое воспроизведение.'},
        {'id':'e2','claim':'TEST_ONLY: расходы взяты из локальной записи','basis':'local_record','locator':'Запись фиктивного запуска','source_url':'','excerpt':'Основной и ошибочный проходы раздельно.','limitations':'Денежный платёж неизвестен.'}]
    body['decisions']=[{'id':'d1','target':'Проверка эффекта replay на новой задаче','action':'Не переносить авторскую экономию без проверки условий','reason':'История содержит только записанные исходы.','evidence_ids':['e1'],'conditions':'Нужны данные независимой проверки на новой задаче.','next_step':'Сопоставить задачу, baseline и критерий качества.'}]
    body['costs'].update(related_run_ids=[related['id']],notes='TEST_ONLY: учитываем ошибочный проход, не скрываем расход.')
    for key,score in [('task',2),('mechanism',2),('evidence',1),('applicability',1),('communication',1)]:
        body['rubric'][key]={'score':score,'note':'TEST_ONLY: причина оценки, нужна дальнейшая проверка.','evidence_ids':['e1']}
    body['editorial']={
        'title':'TEST_ONLY: зачем проверять стратегию на истории попыток',
        'problem':'Каждая новая попытка поиска может быть дорогой. Как проверить другую стратегию без повтора уже записанных попыток?',
        'audience':'Команды автоматизированного поиска кода с проверяемым результатом.',
        'use_case':'Проверка стратегии выбора ветвей для оптимизации вычислительного кода.',
        'mechanism':['Сохранить дерево попыток с известными исходами.','Пройти те же записанные ветви другой стратегией.','Выполнить новый онлайн-поиск для незаписанных продолжений.'],
        'findings':['TEST_ONLY: опубликованный эффект относится к одной конфигурации.'],
        'limitations':['Replay не сообщает результат неизвестной ветви.','Улучшение на истории не гарантирует перенос.'],
        'resources':['Нужны агент, проверяемая оценка и хранение траекторий.','Денежная стоимость неизвестна.'],
        'public_takeaway':'Подходит команде с повторяемым поиском и проверяемым результатом; сначала проверить сопоставимость условий.',
        'next_step':'Определить baseline и проверить, есть ли достаточно полная история альтернатив.',
        'visual_kind':'replay_tree',
        'comparisons':[
            {'label':'TEST_ONLY: затраты фиктивного сравнения','unit':'GPU-ч','baseline_label':'TEST_ONLY baseline','baseline_value':100,'result_label':'TEST_ONLY метод','result_value':40,'conditions':'TEST_ONLY: числа придуманы только для проверки интерфейса, не являются результатами исследования.','evidence_ids':['e1']},
            {'label':'TEST_ONLY: нулевой baseline','unit':'шт.','baseline_label':'TEST_ONLY ноль','baseline_value':0,'result_label':'TEST_ONLY десять','result_value':10,'conditions':'TEST_ONLY: отдельная шкала и проверка корректной нулевой ширины.','evidence_ids':['e1']}]}
    app.store.review.save(run['id'],{'expected_version':0,'body':body})
    server=LocalServer(('127.0.0.1',8799),FixtureHandler);server.app=app;server.fixture_run=run['id'];server.fixture_related=related['id']
    try:
        print('TEST_ONLY ready http://127.0.0.1:8799',flush=True);server.serve_forever(poll_interval=.1)
    finally: app.close();server.server_close()


if __name__=='__main__':main()
