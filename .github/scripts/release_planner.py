"""Issue-based release planning pilot. No AI service, code execution or releases.

Only the configured owner's exact commands in the dedicated plan issue can
approve a fingerprint. Public reports are data, never operational instructions.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

MARKER = '<!-- administrator-release-plan:v1 -->'
OWNER = 'dbzubov'
TITLE = 'План следующего релиза'
PLANNER_POLICY = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_REPORTS = 80
AREAS = [
    ('Установка и обновления', ('установ', 'запуск', 'запуска', 'обновлен', 'smartscreen', 'webview')),
    ('Ключ и подключение AI', ('ключ', 'vsegpt', 'vpn', 'http 400', 'http 504', 'соединен', 'связ', 'api')),
    ('Инструкции', ('инструкц', 'скрин', 'кадр', 'размыт', 'стрелк')),
    ('Встречи', ('встреч', 'транскрип', 'саммари', 'спикер', 'расшифров', 'распознав')),
    ('План-график', ('график', 'гант', 'gantt', 'этап', 'xlsx', 'excel')),
    ('Документы', ('документ', 'пми', 'ткп', 'docx', 'word')),
    ('Проекты и задачи', ('проект', 'задач', 'архив', 'материал')),
]
CHECKS = {
    'Установка и обновления': 'Проверить чистую установку и обновление обычным пользователем, перезапуск и сохранность проектов.',
    'Ключ и подключение AI': 'Проверить хранилище ключа, повтор после ошибки сети и сохранение параметров; исключить ключи из диагностики.',
    'Инструкции': 'Воспроизвести генерацию и правки кадров, проверить версии, разметку и экспорт DOCX.',
    'Встречи': 'Проверить три результата встречи, исходный транскрипт, повтор обработки и сохранение выбранных задач.',
    'План-график': 'Проверить исходные данные, формулы и заливку Ганта в Excel, статусы и редактирование строк.',
    'Документы': 'Проверить вложения, генерацию, повтор после ошибки, выбранную версию и экспорт.',
    'Проекты и задачи': 'Проверить карточку, фильтры, статистику, сохранение и архивирование без потери данных.',
    'Интерфейс и прочее': 'Уточнить шаги, воспроизвести на указанной ОС и проверить затронутый сценарий.',
}
FIELDS = [
    ('версия приложения', ('Версия Administrator',)),
    ('ОС и сборка', ('Версия и сборка Windows', 'ОС и версия', 'Операционная система')),
    ('шаги', ('Шаги воспроизведения',)),
    ('ожидаемый результат', ('Ожидаемый результат',)),
    ('фактический результат', ('Фактический результат, текст ошибки и скриншот', 'Фактический результат')),
]


def labels(issue):
    return {x['name'] if isinstance(x, dict) else x for x in issue.get('labels', [])}


def clean(value, limit=140):
    text = str(value or '')[:4000]
    text = text.replace('\\', '＼')
    text = re.sub(r'https?://\S+', '[ссылка в обращении]', text, flags=re.I)
    text = re.sub(r'(?i)\b(?:sk-|gh[pousr]_|github_pat_)[a-z0-9_-]+', '[ключ скрыт]', text)
    text = re.sub(r'(?i)\b(?:bearer|api[-_ ]?key|password|пароль)\s*[:=]?\s*\S+', '[секрет скрыт]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[email скрыт]', text)
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Do not activate mentions, HTML, links, checkboxes or table cells from titles.
    text = html.escape(text, quote=False).replace('@', '＠')
    for char in ('|', '[', ']', '`', '*', '_', '~'):
        text = text.replace(char, '\\' + char)
    return text[:limit] + ('…' if len(text) > limit else '')


def form_fields(body):
    result = {}
    current = None
    for line in (body or '').splitlines():
        if line.startswith('### '):
            current = line[4:].strip().casefold()
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return {k: '\n'.join(v).strip() for k, v in result.items()}


def report(issue):
    title = (issue.get('title') or '').casefold()
    body = issue.get('body') or ''
    tags = labels(issue)
    explicit = next((area for area, _ in AREAS if 'area:' + area in tags), None)
    # Prefer the reported product component in the title over a generic AI error.
    ordered = [row for row in AREAS if row[0] != 'Ключ и подключение AI'] + [row for row in AREAS if row[0] == 'Ключ и подключение AI']
    area = explicit or next((a for a, words in ordered if any(w in title for w in words)), None)
    if area is None:
        area = next((a for a, words in AREAS if any(w in body.casefold() for w in words)), 'Интерфейс и прочее')
    priority = 'P2 · предварительно'
    if 'priority:critical' in tags or any(w in title for w in ('потеря данных', 'пропали проекты', 'удалились данные')):
        priority = 'P0 · проверить немедленно'
    elif 'priority:high' in tags or any(w in title for w in ('не запускается', 'не устанавливается', 'не могу запустить')):
        priority = 'P1 · предварительно'
    fields = form_fields(body)
    missing = [name for name, aliases in FIELDS if not any(fields.get(a.casefold(), '').strip() not in ('', '_No response_', 'Нет ответа') for a in aliases)]
    status = 'Готово к проверке' if 'needs-verification' in tags else 'В работе' if 'in-progress' in tags else 'К разбору'
    version = fields.get('версия administrator', '')
    system = next((fields[a.casefold()] for a in FIELDS[1][1] if fields.get(a.casefold())), '')
    return {'issue': issue, 'area': area, 'priority': priority, 'missing': missing, 'status': status,
            'version': clean(version, 60) or 'не указана', 'system': clean(system, 70) or 'не указана'}


def candidates(issues, plan_number):
    return sorted((i for i in issues if i.get('state') == 'open' and not i.get('pull_request')
                   and i['number'] != plan_number and not ({'planner-test-exclude', 'later'} & labels(i))), key=lambda i: i['number'])


def fingerprint(issues):
    material = [{k: i.get(k) for k in ('number', 'title', 'body', 'updated_at')} | {'labels': sorted(labels(i))} for i in issues]
    return hashlib.sha256(json.dumps({'policy': PLANNER_POLICY, 'issues': material}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def decision_watermark(comments, previous=0):
    identifiers = [previous]
    for comment in comments:
        if comment.get('user', {}).get('login') == OWNER and comment.get('user', {}).get('type') == 'User':
            if re.fullmatch(r'/approve-plan [a-f0-9]{12}|/request-changes', (comment.get('body') or '').strip()):
                identifiers.append(comment['id'])
    return max(identifiers)



def event_decision_watermark(event, plan_number):
    """Remember revocation even if a command is deleted before the run starts."""
    item = event.get('issue', {})
    comment = event.get('comment', {})
    if item.get('number') != plan_number or item.get('pull_request'):
        return 0
    if comment.get('user', {}).get('login') != OWNER or comment.get('user', {}).get('type') != 'User':
        return 0
    texts = [comment.get('body') or '', event.get('changes', {}).get('body', {}).get('from') or '']
    if any(re.fullmatch(r'/approve-plan [a-f0-9]{12}|/request-changes', text.strip()) for text in texts):
        return int(comment.get('id', 0))
    return 0


def approval(comments, code, has_issues, watermark=0):
    state = None
    for comment in sorted(comments, key=lambda c: (c.get('created_at', ''), c.get('id', 0))):
        if comment.get('id', 0) < watermark:
            continue
        if comment.get('user', {}).get('login') != OWNER or comment.get('user', {}).get('type') != 'User':
            continue
        # Editing a historical command must not approve a new scope silently.
        if comment.get('created_at') != comment.get('updated_at'):
            continue
        command = (comment.get('body') or '').strip()
        if command == '/request-changes':
            state = None
        elif has_issues and command == '/approve-plan ' + code:
            state = comment
    return state


def possible_duplicates(reports):
    result = []
    for pos, left in enumerate(reports):
        a = set(re.findall(r'[а-яёa-z0-9]{3,}', (left['issue'].get('title') or '').casefold())) - {'windows', 'ошибка', 'при'}
        for right in reports[pos+1:]:
            if left['area'] != right['area']:
                continue
            b = set(re.findall(r'[а-яёa-z0-9]{3,}', (right['issue'].get('title') or '').casefold())) - {'windows', 'ошибка', 'при'}
            if len(a & b) >= 3 and len(a & b) / max(1, len(a | b)) >= .55:
                result.append((left['issue']['number'], right['issue']['number']))
    return result[:30]


def render(issues, comments, plan_number, repository, run_url, previous_watermark=0):
    selected = candidates(issues, plan_number)
    code = fingerprint(selected)
    watermark = decision_watermark(comments, previous_watermark)
    overflow = len(selected) > MAX_REPORTS
    accepted = approval(comments, code, bool(selected) and not overflow, watermark)
    reports = [report(i) for i in selected[:MAX_REPORTS]]
    lines = [MARKER, '# План следующего релиза', '',
             'Страница обновляется ботом. Обсуждение и согласование — в комментариях; ручные изменения описания будут перезаписаны.', '',
             f'**Код плана:** `{code}` · **Открытых обращений:** {len(selected)}', '',
             '**Статус:** ' + ('согласован владельцем; ожидает запуска работ в Codex.' if accepted else 'ожидает согласования.' if selected else 'ожидает первых обращений.'), '',
             'Это пилот на правилах: группировка и приоритеты предварительные, причины ошибок ещё не подтверждены. '
             'Платный AI не вызывается. Согласование фиксирует состав работ; код, сборки и релизы бот пока не запускает.', '',
             '## Состав работ', '']
    if overflow:
        lines += [f'**Превышен объём пилота:** показаны первые {MAX_REPORTS} из {len(selected)} обращений. Согласование отключено; разделите объём на релизы вручную. Все обращения доступны в Issues.', '']
    if reports:
        lines += ['| Обращение | Блок | Приоритет | Статус | Версия / ОС | Уточнить |', '| --- | --- | --- | --- | --- | --- |']
        for r in sorted(reports, key=lambda r: (r['priority'], r['issue']['number'])):
            i = r['issue']
            lines.append(f"| [#{i['number']}](https://github.com/{repository}/issues/{i['number']}) {clean(i.get('title'))} | {r['area']} | {r['priority']} | {r['status']} | {r['version']} / {r['system']} | {', '.join(r['missing']) or 'данные заполнены; требуется воспроизведение'} |")
        lines += ['', '## Предлагаемый порядок и проверки', '']
        for area in dict.fromkeys(r['area'] for r in sorted(reports, key=lambda r: r['priority'])):
            refs = ', '.join('#' + str(r['issue']['number']) for r in reports if r['area'] == area)
            lines.append(f'- **{area} ({refs}):** {CHECKS[area]}')
        lines += ['', 'До исправления подтвердить воспроизведение и причину; после — выполнить проверку затронутого сценария и регрессию. '
                  'Технические детали и PR размещаются в закрытом исходном репозитории; публичных данных недостаточно для оценки трудозатрат.', '']
        dupes = possible_duplicates(reports)
        if dupes:
            lines += ['## Возможные повторы', '', *[f'- #{a} и #{b} — похожие заголовки; проверить вручную, обращения не объединены.' for a, b in dupes], '']
    else:
        lines += ['Пока открытых обращений нет. Новую ошибку можно [зарегистрировать через форму](https://github.com/' + repository + '/issues/new/choose).', '']
    deferred = [i for i in issues if i.get('state') == 'open' and not i.get('pull_request') and i['number'] != plan_number and 'later' in labels(i)]
    if deferred:
        lines += ['', f'## Отложенные обращения ({len(deferred)})', '', *[f"- #{i['number']} {clean(i.get('title'))}" for i in deferred[:20]], '', 'Метка `later` исключает обращение из ближайшего релиза; снимите её, чтобы вернуть в план. Полный список — в Issues.', '']
    lines += ['## Согласование', '', f'Команды принимает только **@{OWNER}** в новых комментариях к этой странице:', '',
              (f'- Согласовать текущий состав: `/approve-plan {code}`.' if not overflow else '- Согласование отключено до сокращения объёма пилота.'),
              '- Вернуть на проработку: `/request-changes`.',
              '- Обновить страницу вручную: `/refresh-plan`.', '',
              'При изменении обращения, меток или состава плана код меняется и нужно новое согласование. '
              'Изменение старого комментария не считается согласованием. После согласования передайте ссылку на план в Codex для запуска реализации.', '']
    if accepted:
        lines += [f"Согласование: [комментарий владельца]({accepted['html_url']}).", '']
    lines += ['## Результаты и доставка', '',
              'Метка `later` откладывает обращение. Выполнение отмечается метками `in-progress` и `needs-verification` на обращениях; метки назначает сопровождающий. '
              'Автоматического подтверждения исправления нет. Результаты тестов и ссылки на PR добавляются сопровождающим в комментариях. '
              'Закрытые обращения исключаются из нового плана, история остаётся в Issues.', '',
              '[Опубликованные версии](https://github.com/' + repository + '/releases) · '
              '[Обращения](https://github.com/' + repository + '/issues)', '',
              'Закройте эту страницу, чтобы приостановить бота; после открытия отправьте `/refresh-plan`. '
              'Обновления приложения устанавливаются только вручную. Не прикладывайте API-ключи и конфиденциальные материалы. '
              'Содержимое обращений и вложения не исполняются; вложения бот не скачивает.', '',
              f'[Последняя проверка бота]({run_url})', f'<!-- scope:{code} -->', f'<!-- decision-watermark:{watermark} -->']
    result = '\n'.join(lines) + '\n'
    if len(result) > 60000:
        raise RuntimeError('Plan exceeds safe issue size; split the scope before approving')
    return result


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid repository')
        self.base = 'https://api.github.com/repos/' + repository
        self.token = token

    def call(self, path, method='GET', data=None):
        request = Request(self.base + path, method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                                   'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'},
                          data=json.dumps(data).encode() if data is not None else None)
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def pages(self, path):
        rows = []
        for page in range(1, 21):
            chunk = self.call(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
            rows.extend(chunk)
            if len(chunk) < 100:
                return rows
        raise RuntimeError('More than 2000 records; refusing to silently truncate the plan')


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    if repository != OWNER + '/administrator-releases':
        raise RuntimeError('Planner is scoped to the distribution repository')
    number = int(os.environ['PLAN_ISSUE_NUMBER'])
    client = GitHub(repository, os.environ['GH_TOKEN'])
    plan = client.call(f'/issues/{number}')
    if plan.get('pull_request') or not (plan.get('body') or '').startswith(MARKER):
        raise RuntimeError('Configured issue is not the managed release plan')
    if plan.get('state') != 'open':
        print('Release planner paused: managed issue is closed')
        return
    issues = client.pages('/issues?state=open')
    comments = client.pages(f'/issues/{number}/comments')
    run_url = 'https://github.com/' + repository + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
    match = re.search(r'<!-- decision-watermark:(\d+) -->', plan.get('body') or '')
    watermark = int(match.group(1)) if match else 0
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    event = json.loads(Path(event_path).read_text(encoding='utf-8')) if event_path else {}
    watermark = max(watermark, event_decision_watermark(event, number))
    body = render(issues, comments, number, repository, run_url, watermark)
    # Avoid recursive issue-edited updates caused only by a new run URL.
    canonical = lambda text: re.sub(r'\[Последняя проверка бота\]\([^\n]+\)', '', text or '')
    if canonical(body) != canonical(plan.get('body')):
        client.call(f'/issues/{number}', 'PATCH', {'body': body})
    print('Release plan checked: #' + str(number) + '; open reports: ' + str(len(candidates(issues, number))))


if __name__ == '__main__':
    main()
