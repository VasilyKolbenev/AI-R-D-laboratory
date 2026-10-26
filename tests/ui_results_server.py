"""TEST_ONLY result presentation fixture; never connects to Telegram or a provider."""
from pathlib import Path
import argparse
import json
import threading

from laboratory.server import Handler, Laboratory, LocalServer


class FakeTelegram:
    def __init__(self, *args):
        self.result_deliveries = 0
        self.plan_deliveries = 0

    def status(self):
        return {'configured': True, 'owner_id': 123, 'username': 'TEST_ONLY', 'status': 'TEST_ONLY transport'}

    def bind_workflow(self, *args, **kwargs):
        pass

    def send_result(self, run_id):
        self.result_deliveries += 1
        return {'status': 'sent', 'test_only': True}

    def present_plan(self, run_id):
        self.plan_deliveries += 1
        return {'status': 'sent', 'test_only': True}

    def stop(self):
        pass


class FixtureHandler(Handler):
    def do_GET(self):
        if self.path == '/__test__/stats':
            return self.send({'test_only': True, 'provider_dispatches': 0,
                              'run_id': self.server.fixture_run, 'plan_id': self.server.fixture_plan,
                              'result_deliveries': self.app.telegram.result_deliveries,
                              'plan_deliveries': self.app.telegram.plan_deliveries})
        return super().do_GET()

    def do_POST(self):
        if self.path == '/__test__/shutdown':
            self.send({'test_only': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return super().do_POST()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    def forbidden_runner(*unused):
        raise AssertionError('No provider dispatch is authorized by this UI test')
    app = Laboratory(args.data_dir, runner=forbidden_runner, telegram_factory=FakeTelegram)
    source, _ = app.store.add_source(text='TEST_ONLY: ИИ и speculative decoding', title='TEST_ONLY source')
    long_question = ('TEST_ONLY: где полезен speculative decoding? ' +
                     'Сравни применимость для интерактивного LLM-сервиса, baseline, метрики, инфраструктуру и ограничения. ' * 15 +
                     'TEST_ONLY_END_OF_FULL_QUESTION')
    run = app.store.create_plan({'source_ids': [source['id']], 'question': long_question, 'web_search': False})
    app.store.approve(run['id'], run['plan_hash'], True, 'TEST_ONLY-seeded-report')
    app.store.finish(run['id'], {'status': 'completed', 'text': '''## 1. Краткий вывод
TEST_ONLY: внедрение отложить до выбора нагрузки. <script>window.__resultExecuted=true</script>

## Применимость к задаче
Для длинных ответов; сценарий требует проверки.

## Плюсы
- TEST_ONLY: кандидаты для ускорения decode.

## Ограничения
- Нет собственных измерений.

## Метрики
- TPOT p95: целевой порог неизвестен.

## Self-hosted и неизвестные условия
VRAM и модель пока не выбраны.

## Решение и следующий проверяемый шаг
Определить baseline и нагрузку без аренды GPU.

## Источники
https://example.org/TEST_ONLY-paper

<lab_memory_review>{"comparisons":[]}</lab_memory_review>
''', 'usage': {'test_only': True}, 'raw': {'test_only': True}})
    plan = app.store.create_plan({'source_ids': [source['id']], 'question': 'TEST_ONLY: новый план с памятью?', 'web_search': False})
    server = LocalServer(('127.0.0.1', 8798), FixtureHandler)
    server.app, server.fixture_run, server.fixture_plan = app, run['id'], plan['id']
    try:
        print('TEST_ONLY ready http://127.0.0.1:8798', flush=True)
        server.serve_forever(poll_interval=0.1)
    finally:
        app.close()
        server.server_close()


if __name__ == '__main__':
    main()
