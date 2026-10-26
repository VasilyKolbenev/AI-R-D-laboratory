"""TEST_ONLY automatic presentation fixtures, no real model/Telegram/network."""
import argparse
import json
from pathlib import Path
import threading

from laboratory.server import Handler,Laboratory,LocalServer
from ui_review_server import FakeTelegram


class FixtureHandler(Handler):
    def do_GET(self):
        if self.path=='/__test__/stats':
            return self.send({'test_only':True,'provider_dispatches':0,'run_ids':self.server.fixture_runs})
        return super().do_GET()
    def do_POST(self):
        if self.path=='/__test__/shutdown':
            self.send({'test_only':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        return super().do_POST()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-dir',type=Path,required=True);args=parser.parse_args()
    def forbidden(*unused):raise AssertionError('Real research forbidden')
    app=Laboratory(args.data_dir,runner=forbidden,telegram_factory=FakeTelegram)
    runs=[]
    topics=[('TEST_ONLY: поиск документов',['Превратить запрос в представление для поиска.','Выбрать подходящие фрагменты из индекса.','Передать фрагменты модели для ответа.'],True),
            ('TEST_ONLY: генерация изображений',['Получить исходное шумовое представление.','Преобразовать его по условию текстового запроса.','Декодировать представление в изображение.'],False)]
    for index,(title,steps,complete) in enumerate(topics):
        url='https://example.org/TEST_ONLY-topic-'+str(index)
        excerpt='TEST_ONLY: это вымышленное описание механизма для проверки интерфейса; научных измерений нет.'
        source,_=app.store.add_source(excerpt+' '+url,title=title)
        run=app.store.create_plan({'source_ids':[source['id']],'question':title})
        app.store.approve(run['id'],run['plan_hash'],True,'TEST_ONLY-auto-'+str(index))
        block={'title':title,'problem':'TEST_ONLY: объяснить последовательность технологии без выдуманных метрик.','audience':'TEST_ONLY: читатели исследовательского канала.','use_case':'TEST_ONLY: учебный разбор применимости к своей задаче.','mechanism':steps,'findings':['TEST_ONLY: численных результатов нет.'],'limitations':['TEST_ONLY: собственных измерений нет.'],'resources':['TEST_ONLY: требования неизвестны.'],'public_takeaway':'TEST_ONLY: проверить механизм и условия на своём сценарии.','next_step':'TEST_ONLY: уточнить исходные данные.','evidence':[{'id':'e1','claim':'TEST_ONLY: механизм описан в основном отчёте.','source_url':url,'locator':'TEST_ONLY раздел','excerpt':excerpt,'limitations':'TEST_ONLY: вымышленная фикстура, не доказательство технологии.'}] if complete else [],'comparisons':[]}
        report='## TEST_ONLY\n'+excerpt+'\n'+url+'\n'+'\n'.join(steps)+'\n<lab_presentation>'+json.dumps(block,ensure_ascii=False)+'</lab_presentation>'
        app.store.finish(run['id'],{'status':'completed','text':report,'usage':{},'raw':{'test_only':True,'dispatched':True}})
        runs.append(run['id'])
    server=LocalServer(('127.0.0.1',8808),FixtureHandler);server.app=app;server.fixture_runs=runs
    try:print('TEST_ONLY ready http://127.0.0.1:8808',flush=True);server.serve_forever(poll_interval=.1)
    finally:app.close();server.server_close()


if __name__=='__main__':main()
