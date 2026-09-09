"""Read-only save metadata and the session lobby presentation."""
from datetime import datetime, timezone
import html
from pathlib import Path

TEMPLATE = Path(__file__).with_name('lobby.html')


def lobby_page(store, running=()):
    players = []
    for number, user in enumerate(store.all(), 1):
        saved = None
        try:
            state = store.paths(user['id'])[2] / 'live.state'
            if not state.is_symlink() and state.is_file():
                saved = state.stat().st_mtime
        except (OSError, ValueError):
            pass
        players.append(dict(user, number=number, saved=saved))
    players.sort(key=lambda u: (u['saved'] or 0, u['created_at']), reverse=True)
    cards = []
    for user in players:
        identity, name = html.escape(user['id'], quote=True), html.escape(user['name'], quote=True)
        active = user['id'] in running
        stamp = user['saved']
        date = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp else ''
        saved = (f'<time datetime="{date}" data-time="{stamp}">已保存</time>' if stamp
                 else '<span>尚未保存</span>')
        cards.append(f'''<article class="game-card" data-name="{name}" data-saved="{stamp or 0}" data-created="{user['created_at']}">
<div class="card-top"><span class="slot-number">{user['number']:02d}</span><span class="state {'is-active' if active else ''}">{'运行中' if active else '已存档' if stamp else '新游戏'}</span></div>
<h2><a href="/u/{identity}/">{name}</a></h2>
<div class="saved-at"><span>{'最近保存' if stamp else '准备启程'}</span>{saved}</div>
<div class="card-actions"><a class="continue" href="/u/{identity}/">继续游戏 <span aria-hidden="true">↗</span></a><span class="session-tools" data-session-tools="{identity}"></span></div>
</article>''')
    return (TEMPLATE.read_text().replace('<!-- SESSION_CARDS -->', ''.join(cards))
            .replace('__SESSION_COUNT__', str(len(players)))
            .replace('__RUNNING_COUNT__', str(sum(u['id'] in running for u in players))))
