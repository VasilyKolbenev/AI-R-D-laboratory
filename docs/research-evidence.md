# Evidence workbench / Доказательная лаборатория

Version 0.14.1, 2026-10-23. Local source analysis and controlled API experiments.

## Русский

Новые планы используют сохранённые оригиналы: байты, SHA-256, время, страницы PDF
или строки HTML-таблиц. Присланный текст, полученный документ и неудачный захват
различаются. Захват не исполняет скачанное; поддержка PDF ограничена безопасными
кодеками, размером и числом страниц. Изображения и сложные таблицы не распознаются OCR.
Локальный архив ограничен 50 МиБ; после заполнения нужен экспорт/обслуживание.

В план перед апрувом входят выбранные документы, выдержки, память и записи реестра.
Критик получает документы без ответа исследователя. Третий проход согласует выводы,
сохраняет решения по замечаниям, готовит пост, визуал и необязательную английскую аннотацию.
Для нового v3 поддержан общий предел до 360 секунд с теми же тремя вызовами CLI.
При 360: исследователь 130, критик 100, редактор 110, завершение процессов 20 секунд.
Старые v1/v2 сохраняют прежние бюджеты до 240 секунд. Автоматического повтора нет.
Суточный предел не повышается; неизвестный исход сохраняет использованную резервацию.

Проверка цитаты подтверждает наличие фрагмента в сохранённом документе и точный URL.
Оценка supports/contradicts/insufficient принадлежит модели. Ни согласие ролей, ни хеш
не доказывают истинность исследования. Известное число требует собственной цитаты;
неизвестные и несопоставимые значения не превращаются в нули или график преимущества.
Источники, обнаруженные позже вне снимка, не получают архивную проверку задним числом.

Реестр накапливает определения, единицы, версии, данные, оборудование, нагрузку, основания
и неизвестности. Память предлагает контекст; выбранные записи видны до апрува. Изменение
оригинала показывает затронутые наблюдения, но не переписывает старые публикации.
Обновление захвата запускается владельцем; фонового обхода всех источников нет.

«Доказательства и проверки» содержит реестр, корпус качества, рецепты прикладной проверки,
расчёт стоимости и API-эксперименты. Корпус начинается с неразмеченных отчётов. Человек
отдельно оценивает факты, извлечение чисел, сопоставимость и понятность. Неразмеченное
не считается ошибкой или успехом; автоматического общего процента качества нет.

API-эксперимент имеет отдельный точный план и апрув, максимум 20 запросов за 24 часа.
Поддержан Responses API по фиксированному HTTPS endpoint; API key хранится через Windows
DPAPI отдельно от базы и экспорта. Вход Codex по подписке не используется как API key.
Модель задаёт владелец; конфигурация не делает проверочного платного вызова.
Фиксируются кейсы, две конфигурации, повторения, токены ответа, время и условия остановки.
Перед запросом сохраняется intent. Прерванный/неопределённый исход не повторяется.
Цены и объёмы расчёта — предположения; денежный потолок не гарантируется. Импорт внешних
наблюдений сохраняет происхождение и не выдаётся за эксперимент этой лаборатории.
Локальные модели, произвольный код и self-hosted развёртывание не запускаются.

Публичная версия сохраняется по отдельному действию владельца с точным хешем проекции.
HTML/JSON включают только публичные поля. Английская аннотация доступна, когда она реально
подготовлена в том же ответе. Эти файлы готовы для размещения, но хостинг не включается.
Telegram использует прежний апрув «В очередь» и прежнее расписание. Опубликованные файлы
не подменяются. Резервная копия schema7 включает архив и однократные действия;
импорт schema1–6 сохранён. Ключи API не переносятся в резервной копии.

## English

New plans freeze bounded original captures, selected memory and registry observations before
approval. The critic sees source evidence without the researcher's answer. New v3 plans allow
up to 360 seconds for three CLI calls; at 360, phases receive 130/100/110 seconds plus20 cleanup.
Historical v1/v2 budgets remain unchanged. Daily reservations are preserved; failed or uncertain
dispatches never trigger an automatic model retry.

Exact quotation/URL checks establish captured-text provenance. Semantic support remains a model
judgment, not scientific verification. Unknown or incompatible observations never become plotted
zeros. PDF extraction is bounded and conservative, with no image OCR. Archive capacity is 50 MiB.

The registry accumulates explicit definitions, units, versions and conditions. Source changes
identify affected observations without rewriting history. Existing reports enter the evaluation
corpus ungraded; human factual and readability judgments retain separate denominators.

Controlled API experiments require explicit plans and consent, a separately configured API key,
two fixed arms, bounded cases and a maximum of 20 requests per rolling day. Credentials use
Windows DPAPI and stay outside portable backups. Dispatch intents survive crashes and prohibit
retries. Cost calculations are assumptions, not a guaranteed monetary ceiling. Imported results
remain labelled imports. No local models, arbitrary code or self-hosted deployment are executed.

Public HTML/JSON dossiers use immutable allowlisted projections. An English abstract is included
only when present and validated. Export is local; hosting is not activated. Existing Telegram
publication approval, schedule and frozen published media remain unchanged. Backup schema7 retains
the new evidence and event records while importing schemas1–6.

API reference: https://developers.openai.com/api/docs/guides/text
