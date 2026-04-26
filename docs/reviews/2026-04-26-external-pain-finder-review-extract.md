# External Pain Finder Review — Extracted Source

- Source upload: `doc_77388ada88dc_11.docx` (`11.docx`)
- Original cache path: `/root/.hermes/cache/documents/doc_77388ada88dc_11.docx`
- Extraction date: 2026-04-26
- Extraction method: python-docx document-order paragraph/table extraction
- Note: lightly normalized Markdown/plain-text extraction intended to preserve every substantive thesis from the uploaded review. Compliance/SaaS recommendations are preserved here for auditability even though the requested implementation plan intentionally excludes compliance work for now.

---

1. Executive summary

Я посмотрел не только ваше описание с плейсхолдерами, но и фактический архив pain_finder-main.zip. По коду это уже не просто “парсер болей”, а прототип B2B opportunity intelligence-системы: Reddit/HN/reviews ingestion, LLM-классификация, scoring, deep dive по тредам, macro clustering, Telegram-команды, бюджеты, digest, экспорт и GTM-генерация. То есть амбиции приличные, как будто кто-то решил построить GummySearch, Brandwatch и стажёра-продакта в одном Python-проекте. Храбро. Немного опасно. Местами работает.

Главный вывод: продукт стоит развивать, но не как “ещё один Reddit scraper”. Это слабое позиционирование и юридически скользкое. Развивать стоит как evidence-backed B2B pain and opportunity discovery tool: инструмент, который находит повторяющиеся, монетизируемые рабочие фрустрации, подтверждает их цитатами, частотностью, buyer authority, willingness to pay и провалами текущих решений.

Самые сильные стороны текущей реализации:

уже есть многоступенчатый Reddit ingestion: PRAW, OAuth JSON, public JSON, RSS fallback;

есть structured LLM-анализ по B2B pain, WTP, buyer authority, first-handness, competitor tags;

есть scoring по компонентам, а не просто “AI сказал, боль сильная”;

есть deep dive по треду, digest, экспорт, budget guardrails;

есть eval harness, пусть пока совсем маленький.

Самые большие проблемы:

Reddit compliance риск критический. Reddit прямо ограничивает коммерциализацию, майнинг, scraping и использование Reddit data без express written approval; Data API Terms также дают Reddit право отозвать доступ к API. Это не академическая страшилка, а реальный рыночный риск: GummySearch закрылся для новых пользователей и сослался на Reddit API policies. (Reddit Help)

качество определения “болей” пока нельзя доказать: benchmark всего из 10 seed posts / 10 labels, а это не оценка, а ритуальный костёр для статистики;

текущий classifier сильно зависит от английских hardcoded keywords и может терять recall ещё до LLM;

clustering слабый: hash BoW fallback нестабилен и коллизионен;

UX сейчас больше похож на dev/internal tool, чем на SaaS для стартапов или ресерчеров;

рынок уже содержит прямые аналоги: PainOnSocial, Painpoint.space, Redreach, Linkeddit, Syften, Brand24, Brandwatch, Awario и другие. Некоторые из них уже делают AI-ranked Reddit pain discovery с quotes, scoring и links. (PainOnSocial)

Итоговая оценка сейчас:
5.8 / 10 как коммерческий SaaS
7.0 / 10 как внутренний research MVP / concierge tool
3.5 / 10 как готовый к продаже публичный Reddit SaaS без compliance-решения

2. Что именно я ревьюил

Фактический продукт по архиву:

README.md: описывает систему как Telegram-controlled / Hermes-managed B2B pain discovery system.

scraper.py: Reddit ingestion через PRAW, OAuth JSON, public JSON, RSS fallback.

classifier.py: rule-based + LLM pain classifier.

openrouter.py: LLM prompts, JSON parsing, cache, usage/cost tracking.

pipeline.py: orchestration, scoring, deep dives, reports.

clusterer.py: macro trend clustering.

deduplicator.py, embedder.py: semantic deduplication.

db.py: SQLite schema для pain points, runs, clusters, usage, cache.

eval_harness.py, eval/: начальная оценка качества.

bot.py, scheduler.py, digest_delivery.py: Telegram/scheduled workflow.

generator_gtm.py: генерация GTM assets.

Чего не хватает в пользовательском описании:

название продукта;

конкретная целевая аудитория;

пример входа и выхода;

реальные сценарии использования;

текущие пользователи или интервью;

данные о точности;

юридическая модель доступа к Reddit;

стоимость LLM и ingestion на 1 анализ;

screenshots / UX / dashboard;

реальные отчёты, которые пользователь получает.

Дальше ревью основано на коде, README и публично проверенных аналогах.

3. Сильные стороны

3.1. Это уже больше, чем crawler

В scraper.py:68-82 Reddit ingestion построен как cascade:

PRAW;

OAuth JSON;

public JSON;

RSS fallback.

Это хорошо для MVP: если один метод ломается, система не падает сразу, как гордый, но неподготовленный стартап на первом rate limit.

3.2. Есть top comments и full thread enrichment

В scraper.py:339-418 PRAW-ветка подтягивает top comments и добавляет их к анализируемому тексту. В pipeline.py:307-397 deep dive получает полный тред и отправляет его в LLM.

Это важно, потому что боль часто выражена не в посте, а в комментариях:

“same here”;

“we hacked this with Zapier”;

“we pay for X but hate it”;

“I switched away from Y”.

Ваш код уже смотрит в эту сторону.

3.3. Есть B2B-oriented taxonomy, хоть пока и неполная

В classifier.py:284-317 PainSignal содержит:

pain_level;

willingness_to_pay;

buyer_authority;

first_handness;

post_type;

competitor_tags;

opportunity_bucket;

workflow / impact / consensus / incumbent failure signals.

Это правильное направление. Большинство примитивных Reddit tools делают “keyword alerts”, а вы пытаетесь отделить просто шум от монетизируемой возможности.

3.4. Есть explainable opportunity scoring

В pipeline.py:530-609 считается composite score из компонентов:

pain score;

WTP;

buyer authority;

first-handness;

workflow frequency;

impact;

consensus;

incumbent failure;

recency;

evidence;

penalties.

Это сильнее, чем “LLM ранжирует по вкусу”, потому что scoring можно объяснять, тестировать и калибровать.

3.5. Есть budget guardrails и cache

В openrouter.py:546-617 есть LLM response cache, а в budget.py и pipeline.py:115-118 есть проверки дневного бюджета и paused-флаг.

Для LLM-продукта это критично. Иначе одна неудачная cron-задача превращает бюджет в элегантный дым.

3.6. Есть eval harness

eval_harness.py уже считает:

pain precision / recall / F1;

monetizable precision / recall / F1;

stale leakage;

screening false negatives;

post type confusion;

first-handness accuracy;

buyer authority accuracy.

Это очень правильно. Проблема в размере benchmark, не в идее.

4. Слабые стороны

4.1. Самый большой риск — не NLP, а Reddit policy

Ваш продукт зависит от Reddit data. Reddit Responsible Builder Policy ограничивает коммерциализацию Reddit data, scraping/mining и AI/ML-использование без express written approval. Reddit Data API Terms также позволяют Reddit отозвать доступ к Data APIs. (Reddit Help)

Это значит: если строить публичный SaaS “мы собираем Reddit и продаём инсайты”, без официального разрешения или approved data access модели, продукт может умереть не из-за плохого UX, а из-за письма, написанного юристом. А юристы, как известно, являются природным антагонистом roadmap.

4.2. Direct competitors уже есть

PainOnSocial прямо заявляет, что находит customer pain points from Reddit, выбирает communities, запускает AI analysis, identifies pain patterns, scores by frequency/intensity, показывает real quotes/direct Reddit links и генерирует solution ideas. У него также есть публичные тарифы Starter $19/month и Professional $49/month. (PainOnSocial)

Painpoint.space тоже позиционируется как AI-powered pain point analysis из Reddit communities, с ranked business ideas, impact scores и real examples. (Painpoint)

То есть “AI finds Reddit pain points” уже не уникально. Дифференциация должна быть глубже.

4.3. Recall режется до LLM

В classifier.py:370-397 есть prescreening. В .env.example SCREEN_MIN_RULE_SCORE=2. Это может экономить LLM cost, но убивает recall.

Проблема: настоящие боли часто выражаются без obvious keywords:

“Does anyone have a sane way to reconcile Shopify payouts with QuickBooks?”

Это боль, но не обязательно содержит “hate”, “frustrated”, “problem”, “wish”.

4.4. DSPy schema не совпадает с полной схемой продукта

В dspy_parser.py:67-84 DSPy extraction возвращает только:

category;

severity;

is_monetizable;

pain_level;

WTP;

niche;

competitors;

summary.

Но в полной схеме нужны ещё:

post_type;

first_handness;

buyer_authority;

evidence_spans.

В classifier.py:529-632 DSPy может быть primary path. Это значит, что при включённом DSPy часть важных полей может быть default/inferred, а не реально извлечена. Для продукта, который продаёт “decision-grade insights”, это неприятно.

4.5. Evidence spans не верифицируются

Prompt в openrouter.py:50-91 просит evidence spans. Но код не проверяет, что цитаты реально существуют в исходном посте или комментариях.

Нужно проверять:

exact substring match;

fuzzy match;

source location: post body / title / comment id;

permalink;

confidence.

Иначе LLM может выдать красивую цитату, которой не было. Люди называют это “галлюцинацией”. Машины называют это “ожидаемое поведение статистического попугая”.

4.6. Clustering пока прототипный

В clusterer.py:19-49 fallback embedding — 96-dimensional hash BoW. Комментарий в коде честно признаёт collision risk и нестабильность из-за Python hash seed.

Это нельзя использовать как надёжное topic clustering для SaaS-выдачи. Для MVP — терпимо. Для продукта — нет.

4.7. Benchmark слишком маленький

eval/README.md сам говорит, что целевой benchmark должен быть 100–150 labeled posts, но фактически сейчас около 10 seed posts / 10 labels.

10 примеров — это не benchmark. Это демо для совести.

4.8. Data model не хранит комментарии как first-class сущности

Сейчас комментарии в основном попадают в body/top_comments sample. Но для серьёзного анализа нужно хранить:

comment_id;

parent_id;

author_hash;

score;

created_utc;

depth;

is_op;

permalink;

body;

deletion status.

Иначе вы не можете нормально считать consensus, thread dynamics, author uniqueness и повторяемость.

4.9. UX пока developer-first

Telegram-команды, JSON reports, CSV, Google Sheets, .docx digest — это норм для внутреннего workflow. Но для стартапов, маркетологов и product researchers нужен:

dashboard;

cluster cards;

filters;

saved searches;

source citations;

scoring explanation;

export to Notion/Sheets/Slack;

“show me why this matters”.

Сейчас продукт выглядит как мощная backend-система без очевидного product surface.

4.10. Локальная проверка тестов не подтвердилась

Я пытался прогнать тесты, но pytest не завершился в пределах таймаута, включая targeted test runs. ruff в окружении не установлен. Это не доказывает, что тесты плохие, но означает, что “green CI” я подтвердить не смог.

5. Детальное ревью по разделам

5.1. Product value

Какую реальную задачу решает

Инструмент решает задачу:

“Найти повторяющиеся пользовательские проблемы в публичных онлайн-сообществах и превратить их в продуктовые гипотезы.”

Это полезно для:

indie hackers;

B2B SaaS founders;

product marketers;

customer researchers;

growth teams;

VC / venture studios;

agencies doing niche research.

Но текущая ценность должна быть сформулирована точнее. Не “мы парсим Reddit”, а:

“Мы находим повторяющиеся, подтверждённые цитатами B2B workflow pains, оцениваем частотность, срочность, buyer authority, willingness to pay и показываем, где есть opportunity для продукта.”

Насколько выдача помогает принимать решения

Сейчас выдача помогает частично. Хорошие поля уже есть:

pain_level;

willingness_to_pay;

buyer_authority;

first_handness;

competitor_tags;

opportunity_score;

evidence_spans.

Но decision-making пока слабый без:

нормализованной частотности;

сравнения по сегментам;

confidence score;

source coverage;

trend over time;

user persona extraction;

competitive landscape;

“why now”;

recommended next research action.

Чем лучше обычного Reddit search

Обычный Reddit search даёт посты. Ваш инструмент потенциально даёт:

кластеры проблем;

бизнес-приоритет;

цитаты;

buyer/context signals;

сравнение между нишами;

repeat pattern detection;

GTM hypotheses.

Это и есть value. Но это надо жёстко доказать качеством и UX.

Product value оценка

7 / 10 для внутреннего discovery workflow.
5 / 10 для публичного SaaS сейчас.

Причина: ценность есть, но пока не доказана benchmark’ом, UX и compliance-моделью.

5.2. Качество определения “болей”

Что система уже делает

В classifier.py есть сигналы:

complaint keywords;

unsolved keywords;

wish keywords;

B2B context;

buyer authority;

first-handness;

workflow frequency;

impact;

solved penalty;

shill risk;

consensus in comments.

Это хороший skeleton.

Где границы размыты

Настоящая боль vs мнение

Пример мнения:

“I don’t like Notion.”

Пример боли:

“Our finance team spends 6 hours every Friday reconciling Stripe exports because Notion doesn’t sync with our billing system.”

Нужно отличать эмоциональное отношение от operational consequence.

Жалоба vs вопрос

Вопрос:

“What CRM should I use?”

Боль:

“Every CRM we tried fails when we need to sync custom onboarding stages with HubSpot.”

Ваш classifier может поймать оба как opportunity. Нужно разделять:

generic recommendation request;

solution request with context;

concrete workflow failure;

vendor comparison;

incumbent failure.

Единичный случай vs повторяющийся паттерн

Один пост с высоким score — не паттерн. Паттерн должен иметь:

несколько независимых авторов;

несколько тредов;

повторение во времени;

разные формулировки одной проблемы;

комментарии “same here”;

workaround mentions.

Сильная боль vs слабый сигнал

Сильная боль имеет хотя бы 2–3 признака:

time loss;

money loss;

churn/switching;

compliance/security risk;

current paid workaround;

urgent deadline;

buyer/senior role;

multiple commenters confirm.

Слабый сигнал:

vague annoyance;

no consequence;

no current workaround;

no repeated mentions;

consumer rant;

low context.

5.3. Улучшенная таксономия болей

Рекомендую перейти от category = complaint/unsolved/wish к многоосевой схеме.

[TABLE 1]

Поле | Возможные значения | Зачем нужно

pain_type | workflow friction, missing feature, reliability issue, integration gap, pricing pain, support failure, switching/lock-in, reporting/data gap, compliance/security, procurement friction, knowledge gap | Основной тип проблемы

expression_type | complaint, solution_request, workaround, comparison, feature_request, churn_signal, budget_signal, same_here_consensus | Как боль выражена

user_context | role, industry, company size, tool stack, process, seniority, geography | Кто страдает и в каком процессе

first_handness | first_hand, team_observed, second_hand, hypothetical | Насколько источник близок к проблеме

buyer_authority | buyer, influencer, user, unknown | Может ли человек купить решение

intensity | 1–5 | Насколько боль сильная

frequency | single, thread_consensus, repeated_cross_thread, trend | Насколько боль повторяется

urgency | none, mild, deadline, active_blocker, compliance/revenue_critical | Нужно ли решать сейчас

current_workaround | none, manual, spreadsheet, Zapier, paid_tool, agency, custom_script | Как решают сейчас

willingness_to_pay | 0–5 | Есть ли деньги

incumbent_failure | none, weak, explicit_competitor_failure, switching | Проваливаются ли текущие решения

evidence_quality | no_quote, weak_quote, exact_quote, multi_quote, linked_multi_source | Надёжность вывода

opportunity_type | micro-SaaS, feature, integration, service, content, marketplace, automation, API/tooling | Что можно построить

Пример scoring

Не обязательно такой, но как baseline:

Opportunity Score =

0.18 * intensity

+ 0.14 * frequency

+ 0.14 * willingness_to_pay

+ 0.12 * buyer_authority

+ 0.10 * current_workaround

+ 0.10 * incumbent_failure

+ 0.08 * urgency

+ 0.08 * evidence_quality

+ 0.06 * recency

- penalties(noise, shill_risk, solved_by_obvious_tool, stale_discussion)

Сейчас у вас уже есть похожая логика в pipeline.py:530-609, но её нужно калибровать на размеченном benchmark, а не на интуиции. Интуиция в продактах полезна, но она ещё и прекрасно умеет уверенно ошибаться.

5.4. Data pipeline и парсинг Reddit

Что хорошо

PRAW + OAuth + public JSON + RSS fallback: scraper.py:68-82.

Retry для 429/5xx и Retry-After: scraper.py:832-894.

Feed mix: new, rising, top: scraper.py:115-127.

Search queries per subreddit: scraper.py:147-163.

Dedup внутри batch по post_id: scraper.py:222-245.

Hydration top comments в части веток.

Слабые места

1. Нет полноценной пагинации и ingestion cursors

per_feed_limit ограничен первой выдачей. Search тоже не выглядит как полный crawl по временным окнам. Это значит, что coverage трудно доказать.

Нужно хранить:

subreddit;

feed;

query;

after;

before;

time_window;

last_seen_created_utc;

last_success_at;

fetch_errors.

2. Частотность не нормализована

“10 болей в r/SaaS” и “10 болей в r/smallbusiness” — не одно и то же, если активность сабреддитов отличается.

Нужно считать:

pain_mentions_per_1000_posts

pain_mentions_per_1000_comments

unique_authors_count

unique_threads_count

weekly_delta

3. Удалённые посты и комментарии не обработаны как отдельный кейс

Нужно явно хранить:

is_deleted;

is_removed;

body_available;

deleted_detected_at;

deletion sync / purge logic.

Это важно и для качества, и для compliance.

4. Author name хранится напрямую

В db.py есть author_name. Для продукта лучше:

хешировать author;

не экспортировать raw username по умолчанию;

убирать PII;

добавлять deletion/purge pipeline.

5. Comments не first-class data

Без нормальной таблицы комментариев нельзя хорошо измерить consensus.

Рекомендованная схема:

comments (

comment_id TEXT PRIMARY KEY,

post_id TEXT,

parent_id TEXT,

body TEXT,

body_hash TEXT,

author_hash TEXT,

score INTEGER,

created_utc INTEGER,

depth INTEGER,

is_op BOOLEAN,

is_deleted BOOLEAN,

permalink TEXT,

fetched_at TIMESTAMP

)

6. Compliance gating отсутствует

Нужно добавить в продуктовый workflow:

source policy config;

allowed data sources;

retention policy;

no raw data redistribution mode;

user-owned credentials mode;

approved/licensed data source mode;

audit log.

Reddit policy тут нельзя игнорировать. GummySearch уже стал примером того, как рынок может закончиться не конкурентом, а Terms of Service. (GummySearch)

5.5. NLP / LLM-анализ

Текущий подход

Сейчас используется гибрид:

rule-based prescreen;

DSPy или OpenRouter LLM;

fallback heuristic classifier;

sentiment-ish / keyword signals;

comment signals;

deep dive summarization;

cluster labels;

GTM generation.

Это нормальная MVP-архитектура. Но для качества нужна более строгая валидация.

Проблемы

1. Prompts хорошие, но слишком многое просят за один проход

openrouter.py:50-91 просит LLM определить сразу много полей. Чем больше полей, тем выше шанс, что модель заполнит их “правдоподобно”.

Лучше разделить:

pain detection;

evidence extraction;

business opportunity classification;

scoring;

cluster labeling;

insight summarization.

2. Нет confidence score

Нужно поле:

{

"confidence": 0.0-1.0,

"uncertainty_reason": "...",

"needs_human_review": true/false

}

3. Нет evidence verifier

Должен быть отдельный deterministic step:

For every evidence span:

- find exact match in title/body/comments;

- if no exact match, fuzzy match;

- attach source location;

- if no match, drop span and penalize evidence_quality.

4. Sentiment analysis не равен pain detection

Негативный sentiment может быть:

“This UI is ugly.”

А боль:

“We lose 2 hours every day because the export fails.”

Вторая может быть написана нейтрально. Поэтому sentiment должен быть secondary signal, не classifier.

5. Topic modeling и clustering недостаточно надёжны

Hash BoW fallback — это emergency mode, не clustering strategy.

Лучше:

production embeddings;

HDBSCAN / agglomerative clustering;

centroid + representative examples;

cluster stability score;

duplicate/near-duplicate removal;

cluster label generated only after evidence aggregation.

Надёжный pipeline

Рекомендованный пайплайн:

1. Ingest

Reddit posts/comments with metadata, source policy, deletion status.

2. Normalize

Clean text, language detect, remove boilerplate, hash author, preserve links.

3. High-recall candidate generation

Use broad rules + embeddings + semantic queries.

Do not over-filter with narrow pain keywords.

4. LLM pain classification

Structured JSON:

pain_type, expression_type, intensity, urgency, WTP, context, buyer_authority.

5. Evidence verification

Match every quote to source text.

Attach permalink/comment_id.

6. Comment consensus extraction

same_here_count, workaround_count, alternative_tools, disagreement, shill_risk.

7. Semantic deduplication

Real embeddings, vector index, source-aware dedup.

8. Clustering

Cluster by problem, not by keyword.

Use stable clustering and representative examples.

9. Ranking

Calibrated score with visible components.

10. Validation

Run against benchmark on every release.

Track precision, recall, F1, evidence validity, cluster quality.

11. Human feedback

User marks: useful / not useful / wrong / duplicate / not B2B.

Feed into eval and active learning.

5.6. Метрики качества

Core classification metrics

[TABLE 2]

Metric | Что измеряет | Как считать

Pain precision | Доля найденных болей, которые реально боли | TP / (TP + FP)

Pain recall | Доля реальных болей, которые система нашла | TP / (TP + FN)

Pain F1 | Баланс precision/recall | Harmonic mean

Monetizable precision | Доля “monetizable”, реально имеющих business potential | TP / (TP + FP)

Monetizable recall | Сколько монетизируемых возможностей найдено | TP / (TP + FN)

False positive pain rate | Сколько обычных мнений ошибочно стало болью | FP / predicted positives

Screening FN rate | Сколько болей отрезал prescreen | FN before LLM / all positives

Taxonomy metrics

[TABLE 3]

Metric | Что измеряет

Pain type accuracy | Верно ли определён тип боли

Intensity MAE | Ошибка по шкале интенсивности

Urgency accuracy | Верно ли определена срочность

WTP MAE / rank correlation | Верно ли ранжируется willingness to pay

Buyer authority accuracy | Верно ли определён покупатель/пользователь

First-handness accuracy | Верно ли определён источник боли

Evidence metrics

[TABLE 4]

Metric | Цель

Evidence exact match rate | Цитата реально есть в источнике

Evidence coverage | У скольких выводов есть цитаты

Evidence relevance | Цитата действительно подтверждает боль

Source link validity | Ссылка открывает нужный пост/комментарий

Cluster metrics

[TABLE 5]

Metric | Что измеряет

Cluster purity | В одном кластере одна проблема или мусор

Duplicate rate | Сколько дублей осталось

B-cubed precision/recall | Качество кластеризации по labeled clusters

NMI / ARI | Согласие кластеров с ручной разметкой

Top-N cluster usefulness | Сколько top insights пользователь считает полезными

Business usefulness metrics

[TABLE 6]

Metric | Что измеряет

Insight usefulness rate | % инсайтов, отмеченных как useful

Idea-to-interview conversion | Сколько insights привели к customer interviews

Idea-to-MVP conversion | Сколько идей стали экспериментом

Time saved | Сколько часов ручного research заменено

Repeat user rate | Пользователь возвращается или сбежал к Excel

Export/action rate | Сколько результатов экспортируется/используется

5.7. Конкретный план тестирования

Неделя 1: benchmark

Собрать минимум:

300 posts/comments;

20–40 subreddits;

B2B + B2C + mixed;

hard negatives;

recommendation questions;

rants;

vendor comparisons;

old and fresh posts;

short and long threads.

Разметка:

2 annotators;

label guide;

adjudication;

disagreement log;

Cohen’s kappa или хотя бы agreement rate.

Неделя 2: baseline

Прогнать:

current pipeline;

no prescreen version;

LLM-only version;

rules-only version;

DSPy vs OpenRouter.

Сравнить:

precision;

recall;

F1;

cost per useful insight;

latency;

evidence validity.

Неделя 3: ablations

Проверить, что реально помогает:

comments on/off;

buyer authority on/off;

evidence verifier on/off;

clustering method A/B;

scoring weights A/B.

Неделя 4: user usefulness test

Дать 5–10 users отчёты по их нишам.

Измерить:

какие insights полезны;

какие очевидны;

какие ошибочны;

какие привели к действиям;

сколько времени они сэкономили.

Цель MVP:

Pain precision: >= 0.75

Pain recall: >= 0.60

Evidence exact match: >= 0.95

Monetizable precision: >= 0.65

Top-10 useful insight rate: >= 0.50

Cluster duplicate rate: <= 0.20

5.8. UX и формат результата

Что сейчас

Сейчас UX выглядит как:

Telegram commands;

reports;

digest;

CSV / Sheets;

.docx.

Это удобно для founder/dev workflow, но не достаточно для широкой аудитории.

Идеальный формат результата

Главная единица интерфейса должна быть не пост, а pain cluster.

Pain cluster card

Title:

“Agencies struggle to reconcile ad spend and client reporting across tools”

Opportunity Score: 82/100

Confidence: High

Frequency: 17 mentions / 6 subreddits / 30 days

Intensity: 4/5

WTP: 3/5

Urgency: Medium

Buyer Authority: Founder / agency owner / ops lead

Why it matters:

Teams report weekly manual reconciliation, spreadsheet workarounds, and frustration with existing tools.

Evidence:

1. Quote + Reddit link

2. Quote + Reddit link

3. Comment consensus quote + Reddit link

Affected users:

- small agency founders

- marketing ops leads

- freelancers managing multiple clients

Current workarounds:

- spreadsheets

- Zapier

- manual exports

- Looker Studio hacks

Competitors/tools mentioned:

- Tool A

- Tool B

- Google Sheets

Suggested wedge:

“Automated weekly client reporting reconciliation for small agencies.”

Risks:

- crowded reporting market

- unclear budget for micro-agencies

- may be solved by existing BI tools for larger teams

Фильтры

Обязательные:

source;

subreddit;

time range;

pain type;

industry;

role/persona;

intensity;

WTP;

urgency;

confidence;

first-hand only;

buyer authority;

competitor mentioned;

new / rising / evergreen;

evidence quality.

Dashboard sections

Top opportunities

Trending pains

Competitor failures

Unmet feature requests

High WTP signals

Weak signals to watch

Rejected/noise examples

Coverage and confidence report

Да, rejected examples тоже нужны. Пользователь должен видеть не только “что нашли”, но и “что система намеренно выбросила”. Иначе доверие будет примерно как к LinkedIn growth guru.

6. Сравнение с аналогами

Ниже только реальные инструменты, по которым есть публичная информация. Где информация ограничена, я явно отмечаю.

[TABLE 7]

Инструмент | Категория | Reddit? | Находит боли или упоминания? | AI / clustering / scoring | Экспорт / отчёты | ЦА | Сильные стороны | Слабые стороны | Чем ваш может отличаться

PainOnSocial | Customer pain discovery | Да | Именно pain points из Reddit | AI analysis, pain patterns, scoring by frequency/intensity, quotes/links, solution ideas | Публично заявлены ranked pain points, quotes, links; тарифы Starter/Professional | Founders, growth teams, market researchers | Очень близкий прямой конкурент; уже понятный UX и pricing | Неизвестна фактическая точность; возможно generic | Ваш шанс: глубже B2B, buyer authority, WTP, evidence verification, benchmark transparency (PainOnSocial)

Painpoint.space | AI Reddit pain analysis | Да | Pain points / business ideas | AI-ranked opportunities, impact scores, real examples | Публично заявлены ranked results | Entrepreneurs, indie hackers | Простая ценность: subreddit → opportunities | Публичной информации о методологии мало | Ваш шанс: более профессиональный research workflow, multi-source, scoring explainability (Painpoint)

GummySearch | Reddit audience research | Да, но продукт закрыт для новых пользователей | Customer discovery themes, including pain/anger, solution requests, money talk | Audience/theme analysis | Был полноценный research workflow | Founders, marketers, investors | Сильный market benchmark; понятные themes | Закрылся 30 Nov 2025 из-за Reddit API policy restrictions; не рабочий аналог для новых пользователей | Главный урок: compliance нельзя игнорировать (GummySearch)

Syften | Keyword monitoring | Да | Упоминания по keywords, не боли | Нет явного pain taxonomy; alerting | Alerts | Founders, marketers, support, sales | Хорош для быстрых keyword alerts | Не превращает шум в opportunity clusters | Ваш инструмент лучше в analysis; Syften лучше в простом monitoring (Syften)

F5Bot | Free keyword alerts | Да, плюс Hacker News/Lobsters | Упоминания | Нет fuzzy/regex, keyword matching по titles/comments | Email alerts | Indie hackers, devs | Бесплатный и простой | Не pain discovery, не scoring | Ваш инструмент должен продавать не alerts, а принятие решений (F5Bot)

Redreach | Reddit marketing / lead gen | Да | Opportunities/leads по Reddit conversations | AI relevance filter, daily digests, high-ranking Reddit opportunities | Digests | Marketers, founders, sales/growth | Хорошо ложится на acquisition workflow | Больше про traffic/customers, меньше про deep product research | Ваш шанс: research-grade insights, не только outreach/lead gen (redreach.ai)

Linkeddit | Reddit lead generation | Да | Buying intent, recommendations, frustration signals | Scores users on buying intent | Lead workflow | Sales / founders | Сильный sales use case | Не обязательно анализирует рынок/кластеры проблем | Ваш продукт может быть pre-sales research layer (Linkeddit)

ForumScout | AI social listening / alerts | Да | Mentions, brand/competitor monitoring | AI social listening, sentiment, share of voice; Reddit keyword alerts | Alerts / monitoring | Brands, marketers | Хорош для monitoring и competitive intelligence | Не сфокусирован на product pain discovery | Ваш шанс: problem taxonomy + opportunity scoring (forumscout.app)

Brand24 | Social listening | Да | Mentions, sentiment, topics | AI social listening, sentiment, topic analysis | Reports / dashboards | Marketing, PR, brand teams | Зрелый social listening продукт | Не специализирован на startup idea discovery | Ваш продукт может быть дешевле/фокуснее для B2B discovery (Brand24)

Brandwatch | Enterprise social listening | Да, официальный Reddit partner / firehose | Mentions and social intelligence | Enterprise analytics | Enterprise dashboards | Enterprise brands | Сильнейшее покрытие, compliance, enterprise-grade | Дорого, сложно, не indie/startup-focused | Ваш продукт не выиграет coverage; может выиграть focus and workflow (social-media-management-help.brandwatch.com)

Sprout Social | Social media management/listening | Да, expanded Reddit support | Brand/customer conversations | AI-powered social solutions, listening/engagement | Enterprise reports | Social/media teams | Enterprise workflow, Reddit engagement | Не focused на pain discovery/product ideas | Ваш продукт должен быть research tool, не social suite (support.sproutsocial.com)

Awario | Social listening | Да | Mentions, sentiment, alerts | Sentiment analysis, reports | Exportable reports, alerts | Brands, marketers | Хороший general monitoring | Не pain-specific | Ваш шанс: deeper B2B opportunity analysis (awario.com)

Apify Reddit Pain Finder Actor | No-code scraping / actor | Да | Заявляет pain types и ranking | Classifies pain types, ranks discussions; качество публично не доказано | Через Apify workflow | Builders, scrapers | Быстро подключить как actor | Community actor, публичная надёжность ограничена | Ваш шанс: полноценный продукт, eval, UX, compliance story (Apify)

7. Возможности для дифференциации

7.1. Не “Reddit pain finder”, а “B2B opportunity intelligence”

Плохое позиционирование:

“AI finds pain points on Reddit.”

Так уже делают PainOnSocial и Painpoint.space. (PainOnSocial)

Сильнее:

“Find recurring, monetizable B2B workflow failures with verified quotes, buyer authority, WTP signals, competitor failure patterns and decision-ready opportunity scores.”

7.2. Evidence-first подход

Сделать принцип:

“No quote, no insight.”

Каждый вывод должен иметь:

цитату;

ссылку;

post/comment id;

timestamp;

match confidence;

source context.

Это отличит продукт от generic LLM summarizers.

7.3. Benchmark transparency

Публиковать:

pain precision;

recall;

evidence exact match rate;

cluster quality;

cost per useful insight.

Рынок AI-инструментов переполнен магическим дымом. Прозрачная оценка качества — дифференциация.

7.4. B2B buyer authority scoring

Многие tools находят “люди жалуются”. Ваш edge:

“Этот человек похож на покупателя или просто случайно орёт в интернет?”

Поля:

founder;

ops lead;

product manager;

agency owner;

developer;

freelancer;

hobbyist;

student;

unknown.

7.5. Competitor failure radar

Очень сильная фича:

“Покажи recurring complaints about competitors where users mention switching, workarounds, or pricing frustration.”

Это можно продавать B2B SaaS growth/product teams.

7.6. Multi-source triangulation

У вас уже есть HN и review-source ingestion. Это важно.

Одна Reddit-боль — слабый сигнал.
Reddit + HN + reviews + forum comments — сильнее.

8. Рекомендации по улучшению

8.1. Product

Сформулировать ICP: B2B SaaS founders / product marketers / growth researchers.

Убрать generic “startup ideas” как основной use case.

Сделать основной workflow:
niche → pain clusters → evidence → opportunity score → next research actions.

Добавить “confidence & coverage” в каждый отчёт.

Не продавать raw Reddit data. Продавать analysis workflow, preferably with compliant data access.

8.2. Data pipeline

Добавить ingestion cursors и pagination.

Хранить comments отдельно.

Хешировать author names.

Добавить deletion/purge job.

Добавить rate limit token bucket.

Логировать coverage:

fetched posts;

fetched comments;

skipped deleted;

skipped duplicates;

failed requests;

source method used.

Добавить per-subreddit baseline activity.

8.3. Classifier

Сделать high-recall candidate generation.

Ослабить hardcoded keyword prescreen.

Добавить semantic candidate retrieval.

Разделить:

pain detection;

business opportunity scoring;

evidence extraction;

cluster labeling.

Исправить DSPy schema, чтобы она возвращала те же поля, что OpenRouter path.

Добавить confidence и uncertainty reason.

8.4. LLM validation

Проверять evidence spans.

Добавить second-pass verifier.

Сохранять raw LLM payload.

Сравнивать model versions.

Делать deterministic JSON schema validation.

Дропать или понижать insights без проверяемой evidence.

8.5. Clustering

Убрать hash BoW как production path.

Использовать real embeddings.

Добавить vector DB или хотя бы FAISS/pgvector для роста.

Кластеризовать problem statements, не raw posts.

Добавить cluster stability score.

Показывать representative examples.

8.6. UX

Сделать dashboard cluster cards.

Добавить filters.

Добавить score explanation.

Добавить source drilldown.

Добавить user feedback buttons:

useful;

not a pain;

duplicate;

too generic;

wrong segment.

Экспорт:

CSV;

Google Sheets;

Notion;

Slack digest;

PDF/Docx report.

8.7. Compliance

Зафиксировать legal stance до публичного запуска.

Проверить Reddit API terms с юристом.

Не использовать scraping/public JSON как commercial backbone без approval.

Рассмотреть:

bring-your-own Reddit credentials;

approved API access;

licensed data provider;

internal research-only mode;

no raw data redistribution.

Добавить PII redaction and retention policy.

9. Рыночное позиционирование

Лучшее позиционирование

Evidence-backed B2B pain discovery and opportunity scoring from Reddit, HN and customer-review sources.

Не:

“Парсер болей.”

А:

“Инструмент для продуктовых и growth-команд, который находит повторяющиеся B2B workflow pains, подтверждает их цитатами, оценивает WTP и помогает выбрать продуктовую возможность.”

Целевая аудитория

Самая сильная:

B2B SaaS founders на стадии idea validation / pivot.

Product marketers ищут competitor pain и messaging.

Growth researchers ищут acquisition angles.

Venture studios / agencies делают niche research.

Indie hackers, но они чувствительны к цене.

Слабее:

enterprise brands: у них уже Brandwatch/Sprout/Brand24;

generic marketers: им нужны mentions, не product opportunities;

consumer app founders: слишком шумный сегмент.

Основной use case

“Я выбираю нишу или feature wedge. Покажи мне recurring pains, кто страдает, насколько это срочно, чем люди сейчас обходятся, какие tools ругают, и есть ли сигнал готовности платить.”

USP

Verified B2B pain clusters with quotes, buyer context, frequency, WTP, competitor failure signals and explainable opportunity scoring.

Pricing logic

Не конкурируйте напрямую с PainOnSocial по $19/month, если у вас продукт тяжелее и B2B-focused. PainOnSocial уже имеет low-price public plans. (PainOnSocial)

Лучше:

Private beta / concierge

$500–$2,000 за niche research report;

$1,500–$5,000 за monthly research retainer для agencies / venture studios.

SaaS after compliance

[TABLE 8]

Plan | Цена | Для кого | Ограничения

Starter | $49–$99/mo | Indie / solo founder | 3 monitored niches, limited reports

Pro | $199–$399/mo | B2B founders / marketers | 10 niches, weekly digests, exports

Team | $799–$1,500/mo | Product/growth teams | seats, dashboards, competitor tracking

Enterprise | Custom | Larger teams | compliance, SSO, custom sources, retention controls

MVP фичи

Сделать обязательно:

compliant ingestion path;

subreddit/niche setup;

pain taxonomy;

evidence verification;

cluster cards;

opportunity scoring;

filters;

export;

benchmark metrics;

feedback loop.

Отложить:

GTM copy generator;

fancy Telegram flows;

multi-agent “Hermes” complexity;

automatic landing page generation;

massive multi-source crawling;

auto outreach;

“AI founder assistant” разрастание, потому что продукт и так уже пытается стать департаментом.

10. Риски и mitigation

[TABLE 9]

Риск | Серьёзность | Что может случиться | Mitigation

Reddit API / commercial use | Критическая | API access revoked, legal/compliance block | Written approval, licensed provider, BYO credentials, no raw data resale, legal review (Reddit Help)

Scraping/public JSON reliance | Высокая | Источник ломается, rate limits, policy risk | Approved OAuth, rate limits, source policy config

GummySearch-like shutdown | Высокая | Продукт теряет основной data source | Compliance-first model; diversify HN/reviews/forums; don't rely only on Reddit (GummySearch)

LLM hallucinations | Высокая | Пользователь принимает ложный insight | Evidence verifier, quote matching, confidence score

False positives | Высокая | Обычные мнения становятся “opportunities” | Benchmark, hard negatives, human feedback

False negatives | Средняя/высокая | Система пропускает скрытые боли | High-recall semantic candidate generation

Privacy / PII | Высокая | Usernames/PII попадают в экспорт | Hash authors, redact PII, retention/deletion policy

Cost explosion | Средняя | LLM bills растут | Real pricing config, cache, budget, batching

Weak clustering | Средняя | Дубли/мусорные кластеры | Real embeddings, cluster eval, stability metrics

Product commoditization | Высокая | PainOnSocial/Painpoint/lead-gen tools выглядят такими же | B2B specificity, verified evidence, benchmark transparency, competitor failure radar

Enterprise competition | Средняя | Brandwatch/Sprout/Brand24 выигрывают coverage | Не конкурировать coverage; конкурировать workflow/focus

Legal ambiguity for users | Средняя | Клиенты боятся использовать | Clear data policy, approved access, terms, audit logs

Bad UX | Средняя | Инсайты есть, но ими никто не пользуется | Dashboard, cluster cards, filters, exports

Model drift | Средняя | Результаты меняются между runs | Versioning, fixed prompts, eval on every release

Bias by subreddit selection | Средняя | Выводы не репрезентативны | Coverage report, normalized frequency, source diversity

11. Итоговая оценка по критериям

[TABLE 10]

Критерий | Оценка | Комментарий

Полезность | 7.0 | Задача реальная, особенно для B2B discovery

Точность | 5.0 | Хорошая архитектурная задумка, но benchmark слишком мал

Техническая надёжность | 6.0 | Есть fallbacks/retries/cache, но нет полноценной pagination/coverage/compliance layer

Дифференциация | 4.5 | Direct competitors уже есть; нужен sharper B2B edge

Монетизация | 5.0 | Можно монетизировать, но Reddit risk давит

Масштабируемость | 5.0 | SQLite и O(n²)/manual clustering упрутся

Defensibility | 3.5 | Без proprietary benchmark, workflow и compliance почти нет защиты

Готовность к MVP | 7.0 | Для private/internal MVP достаточно близко

Готовность к продаже | 3.5 | Не хватает UX, compliance, доказанной точности

Общая оценка | 5.8 / 10 | Развивать стоит, но с разворотом в сторону evidence-backed B2B research

12. 10 главных проблем

Нет ясной compliance-модели для коммерческого использования Reddit data.

Позиционирование “Reddit pain finder” уже занято прямыми конкурентами.

Benchmark слишком маленький, точность не доказана.

Prescreen может убивать recall до LLM.

Evidence spans не проверяются на фактическое наличие в источнике.

DSPy path возвращает неполную схему.

Clustering нестабилен и недостаточно semantic.

Comments не хранятся как полноценные сущности.

Frequency не нормализована по активности сабреддитов.

UX пока internal/dev-first, не SaaS-first.

13. 10 самых важных улучшений

Зафиксировать legal/compliance path для Reddit.

Расширить benchmark до 300–500 размеченных примеров.

Добавить evidence verifier.

Перестроить taxonomy на multi-axis pain model.

Сделать comments first-class data.

Ослабить keyword prescreen и добавить semantic high-recall retrieval.

Перейти на real embeddings + stable clustering.

Добавить normalized frequency and trend metrics.

Сделать dashboard с pain cluster cards.

Добавить user feedback loop и active learning.

14. 5 быстрых wins

Исправить DSPy schema: пусть возвращает post_type, first_handness, buyer_authority, evidence_spans.

Добавить quote verifier: проверять, что evidence spans реально есть в исходном тексте.

Показать score breakdown в digest/export: почему score 82, а не просто “магия”.

Добавить 50 hard negatives в eval: generic questions, opinions, consumer rants, solved issues.

Добавить coverage metrics в report: fetched/skipped/duplicates/comments/source method.

15. 5 стратегических фич

Competitor Failure Radar
Кластеры жалоб на конкретные tools: pricing, missing features, lock-in, bad support.

Verified Pain Clusters
Каждая проблема подтверждена несколькими independent sources and quotes.

Buyer/WTP Intelligence
Не просто “люди жалуются”, а “кто может купить и почему”.

Trend & Frequency Normalization
Pain mentions per 1,000 posts/comments, weekly growth, freshness.

Research-to-Action Workflow
Из pain cluster → interview questions → ICP hypothesis → MVP wedge → messaging.

16. Roadmap 30 / 60 / 90 дней

30 дней: сделать систему измеримой и менее хрупкой

Цель: доказать, что classifier и evidence работают лучше ручного guessing.

Tasks:

определить финальную taxonomy;

расширить benchmark до 150 examples;

добавить hard negatives;

исправить DSPy schema;

добавить evidence exact/fuzzy verifier;

добавить confidence score;

добавить comments table;

добавить ingestion coverage metrics;

добавить score breakdown в exports;

настроить CI так, чтобы pytest реально завершался;

отключить production reliance на hash BoW clustering.

Deliverable:

MVP research report:

Top 20 pain clusters for one niche,

each with verified quotes, score breakdown, and confidence.

60 дней: сделать usable product surface

Цель: пользователь должен работать с кластерами, не с JSON.

Tasks:

dashboard или хотя бы web report;

cluster cards;

filters;

source drilldown;

feedback buttons;

normalized frequency;

trend detection;

competitor tags view;

Google Sheets/Notion export;

benchmark report v1;

clear data retention / privacy policy.

Deliverable:

Private beta for 5–10 B2B founders/researchers.

Measure useful insight rate and time saved.

90 дней: подготовить коммерческий pilot

Цель: понять, можно ли продавать это без самоуничтожения на Reddit policy.

Tasks:

legal review / compliance plan;

approved data access strategy;

pricing experiment;

onboarding flow;

saved niches;

weekly digest;

competitor failure radar;

multi-source triangulation with HN/reviews;

customer interview workflow;

team/agency report format;

case studies from beta.

Deliverable:

Paid pilot:

3–5 customers paying for niche research or monthly monitoring.

17. Финальный вердикт

Развивать стоит. Но не в текущем позиционировании “парсер болей с Reddit”.

Такой продукт слишком легко сравнить с PainOnSocial, Painpoint.space, Syften, F5Bot, Redreach, Linkeddit и social listening suites. А если вы ещё и будете коммерчески использовать Reddit data без аккуратной модели доступа, то получите не конкуренцию, а административное удушение в красивой упаковке Terms of Service.

Правильное направление:

B2B opportunity intelligence:

verified pain clusters, buyer context, willingness-to-pay signals,

competitor failure patterns, normalized frequency, and decision-ready reports.

Самая рациональная стратегия:

Начать как private beta / concierge research tool.

Продавать не доступ к данным, а готовые decision-grade opportunity reports.

Параллельно решить Reddit compliance.

Построить benchmark и evidence verification.

Потом превращать в SaaS.

Если сделать только crawler + LLM summary, продукт будет легко копируемым и юридически уязвимым. Если сделать доказательный B2B research engine с прозрачной точностью и проверяемыми цитатами, шанс есть. И даже неплохой, что уже почти подозрительно приятно.
