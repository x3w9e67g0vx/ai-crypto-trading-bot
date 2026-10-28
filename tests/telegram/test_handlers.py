from app.game.models import Badge, ChatLeagueMember, Player
from tests.telegram.conftest import buttons, texts


def _player(session_factory, telegram_id=1001):
    with session_factory() as db:
        return db.query(Player).filter_by(telegram_id=telegram_id).one_or_none()


def test_start_shows_disclaimer_and_play_button(harness, session_factory):
    calls = harness.message("/start")

    [text] = texts(calls)
    assert "18+" in text and "виртуальн" in text
    play = [button for button in buttons(calls[-1]) if button.web_app]
    assert play and play[0].web_app.url == "https://example.test/miniapp"
    assert _player(session_factory).nickname == "alice"


def test_start_in_english(harness):
    [text] = texts(harness.message("/start", lang="en"))
    assert "virtual" in text


def test_start_with_ref_records_referral(harness, session_factory):
    harness.message("/start", user_id=1, username="inviter")
    inviter = _player(session_factory, 1)

    harness.message(f"/start ref_{inviter.id}", user_id=2, username="friend")

    assert _player(session_factory, 2).referred_by_id == inviter.id
    with session_factory() as db:
        assert db.query(Badge).filter_by(player_id=inviter.id, code="recruiter").count() == 1


def test_banned_player_gets_banned_text(harness, session_factory):
    harness.message("/start")
    with session_factory() as db:
        db.query(Player).update({"is_banned": True})
        db.commit()

    for command in ("/start", "/rank", "/play"):
        [text] = texts(harness.message(command))
        assert "заблокирован" in text


def test_rank_shows_both_seasons(harness):
    harness.message("/start")
    [text] = texts(harness.message("/rank"))

    assert "Спринт" in text and "Неделя" in text
    assert "t.me/veydranox_bot?start=ref_" in text
    assert "Бронза" in text


def test_play_learn_help(harness):
    calls = harness.message("/play")
    assert any(button.web_app for button in buttons(calls[-1]))
    assert texts(harness.message("/learn"))
    [help_text] = texts(harness.message("/help"))
    for command in ("/play", "/rank", "/learn", "/settings", "/league"):
        assert command in help_text
    assert "/admin" not in help_text


def test_settings_toggle(harness, session_factory):
    harness.message("/start")
    calls = harness.message("/settings")
    data = [button.callback_data for button in buttons(calls[-1])]
    assert "set:notify_overtaken" in data and "set:lang" in data

    calls = harness.callback("set:notify_overtaken")
    assert _player(session_factory).notify_overtaken is False
    assert any(type(call).__name__ == "EditMessageText" for call in calls)

    harness.callback("set:lang")
    assert _player(session_factory).language == "en"


def test_league_in_group_and_join_callback(harness, session_factory):
    calls = harness.message("/league", chat_id=-100, chat_type="supergroup", title="Friends")
    [text] = texts(calls)
    assert "Friends" in text
    join = next(button for button in buttons(calls[-1]) if button.callback_data.startswith("league:join:"))

    calls = harness.callback(join.callback_data, chat_id=-100, chat_type="supergroup")
    harness.callback(join.callback_data, chat_id=-100, chat_type="supergroup")

    with session_factory() as db:
        assert db.query(ChatLeagueMember).count() == 1
    edited = [call for call in calls if type(call).__name__ == "EditMessageText"]
    assert edited and "alice" in edited[0].text


def test_private_commands_ignored_in_groups(harness):
    for command in ("/start", "/play", "/rank", "/learn", "/settings", "/help"):
        assert harness.message(command, chat_id=-100, chat_type="group", title="g") == []


def test_league_in_private_explains_groups(harness):
    [text] = texts(harness.message("/league"))
    assert "груп" in text


def test_nickname_is_escaped(harness):
    calls = harness.message("/league", chat_id=-100, chat_type="group", title="<b>x</b>")
    assert "&lt;b&gt;x&lt;/b&gt;" in texts(calls)[0]
