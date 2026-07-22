"""Tests for the Discord-adapter behaviour added in Phase B.

Covers channel-unreachable tracking, the germination confirmation gate and
help pagination — all in ``bot.py``, which is otherwise untested since it is
the thin Discord I/O layer, not pure logic. Discord objects (interactions,
channels, messages) are faked with ``unittest.mock`` rather than constructed
for real, since discord.py's own classes need a live gateway connection to be
useful; the code under test — timestamp bookkeeping, branching on existing
state, page construction — has no such dependency once the Discord-shaped
inputs are stood in for. No ``pytest-asyncio`` is added: async entry points
are driven with ``asyncio.run`` from ordinary ``def test_...`` functions,
matching the rest of this suite's plain-pytest style.
"""

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock

import bot
import moisture
import render
import storage
import structure


def _make_state(
    guild_id: int = 1,
    channel_id: int | None = 100,
    message_id: int | None = None,
    channel_unreachable_since: float | None = None,
) -> storage.GuildState:
    """A minimal, already-germinated guild state for wiring into a client."""
    return storage.GuildState(
        guild_id=guild_id,
        structure=structure.germinate(seed=1),
        moisture=moisture.MIN_MOISTURE,
        last_update=0.0,
        channel_id=channel_id,
        message_id=message_id,
        channel_unreachable_since=channel_unreachable_since,
    )


def _make_channel(channel_id: int = 100) -> MagicMock:
    """A fake text channel with just the attributes the code under test reads."""
    channel = MagicMock()
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    return channel


def _make_interaction(guild_id: int | None = 1, user_id: int = 42) -> MagicMock:
    """A fake interaction with awaitable response methods, matching what
    ``require_guild``, the commands and the views under test actually call."""
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())
    return interaction


# --- 2a: channel-unreachable state -----------------------------------------


def test_refresh_sets_unreachable_timestamp_on_first_failure() -> None:
    """The first time the bound channel can't be resolved, the field is stamped."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id)
    client._text_channel = AsyncMock(return_value=None)

    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is not None


def test_refresh_does_not_overwrite_existing_unreachable_timestamp(monkeypatch) -> None:
    """A second consecutive failure leaves the first-recorded timestamp untouched."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id)
    client._text_channel = AsyncMock(return_value=None)

    monkeypatch.setattr(bot.time, "time", lambda: 1000.0)
    asyncio.run(client.refresh_channel_message(guild_id))
    first_timestamp = client._states[guild_id].channel_unreachable_since
    assert first_timestamp == 1000.0

    monkeypatch.setattr(bot.time, "time", lambda: 2000.0)
    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since == first_timestamp


def test_refresh_clears_unreachable_timestamp_once_channel_resolves() -> None:
    """Once the channel resolves again, the recorded timestamp is cleared to None."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, channel_unreachable_since=12345.0)

    fake_message = MagicMock()
    fake_message.id = 999
    fake_channel = _make_channel(channel_id=100)
    fake_channel.get_partial_message = MagicMock()
    fake_channel.send = AsyncMock(return_value=fake_message)
    client._text_channel = AsyncMock(return_value=fake_channel)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is None
    assert client._states[guild_id].message_id == 999


def test_plant_command_shows_unreachable_note_when_set(monkeypatch) -> None:
    """/plant prepends the unreachable-channel note when the field is set."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(
        guild_id=guild_id, message_id=500, channel_unreachable_since=999.0
    )
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs["content"] is not None
    assert "epiphyte-channel" in kwargs["content"]


def test_plant_command_omits_note_when_channel_reachable(monkeypatch) -> None:
    """/plant sends no extra content when the bound channel is fine."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(
        guild_id=guild_id, message_id=500, channel_unreachable_since=None
    )
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs["content"] is None


# --- 2b: first-time germination gating -------------------------------------


def test_epiphyte_channel_shows_confirmation_for_new_guild(monkeypatch) -> None:
    """A guild with no plant_state row gets the confirmation view, not a plant."""
    client = bot.EpiphyteClient()
    client.germinate_plant = AsyncMock()
    monkeypatch.setattr(bot, "client", client)

    guild_id = 7
    interaction = _make_interaction(guild_id=guild_id, user_id=42)
    channel = _make_channel(channel_id=55)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs["view"], bot.ConfirmGerminationView)
    client.germinate_plant.assert_not_awaited()
    assert guild_id not in client._states


def test_confirm_button_germinates_exactly_once() -> None:
    """Pressing confirm germinates exactly once, with the view's guild/channel."""
    fake_client = MagicMock()
    fake_client.germinate_plant = AsyncMock()
    fake_client.refresh_channel_message = AsyncMock()
    original_client = bot.client
    bot.client = fake_client
    try:
        channel = _make_channel(channel_id=321)
        view = bot.ConfirmGerminationView(guild_id=99, channel=channel, author_id=1)
        interaction = _make_interaction(guild_id=99, user_id=1)

        asyncio.run(view.confirm.callback(interaction))

        fake_client.germinate_plant.assert_awaited_once()
        call_args = fake_client.germinate_plant.await_args.args
        assert call_args[0] == 99
        assert call_args[1] == 321
        fake_client.refresh_channel_message.assert_awaited_once_with(99)
    finally:
        bot.client = original_client


def test_epiphyte_channel_rebind_skips_confirmation(monkeypatch) -> None:
    """A guild with an existing row never sees the view; rebind runs directly."""
    client = bot.EpiphyteClient()
    guild_id = 3
    client._states[guild_id] = _make_state(guild_id=guild_id, channel_id=10, message_id=None)
    client.refresh_channel_message = AsyncMock()
    monkeypatch.setattr(bot, "client", client)
    view_cls = MagicMock()
    monkeypatch.setattr(bot, "ConfirmGerminationView", view_cls)

    interaction = _make_interaction(guild_id=guild_id, user_id=1)
    channel = _make_channel(channel_id=20)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    view_cls.assert_not_called()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "view" not in kwargs
    assert client._states[guild_id].channel_id == 20


def test_confirmation_timeout_creates_no_state() -> None:
    """A view that times out without a press leaves no state row behind."""
    fake_client = MagicMock()
    fake_client.germinate_plant = AsyncMock()
    original_client = bot.client
    bot.client = fake_client
    try:
        channel = _make_channel(channel_id=8)
        view = bot.ConfirmGerminationView(guild_id=55, channel=channel, author_id=1)

        asyncio.run(view.on_timeout())

        fake_client.germinate_plant.assert_not_awaited()
    finally:
        bot.client = original_client


def test_confirmation_timeout_disables_button_and_edits_message() -> None:
    """A timed-out view greys out its button and rewrites the message with a note."""
    channel = _make_channel(channel_id=8)
    view = bot.ConfirmGerminationView(guild_id=55, channel=channel, author_id=1)
    original_content = (
        "🌱 This server doesn't have a plant yet. Starting one here creates "
        "**one permanent plant tied to this server's id**"
    )
    fake_message = MagicMock()
    fake_message.edit = AsyncMock()
    view.message = fake_message

    asyncio.run(view.on_timeout())

    assert view.confirm.disabled is True
    fake_message.edit.assert_awaited_once()
    edit_kwargs = fake_message.edit.await_args.kwargs
    assert "expired" in edit_kwargs["content"]
    assert edit_kwargs["content"] != original_content


# --- 2c: help pagination -----------------------------------------------------


def test_help_pages_count_and_titles() -> None:
    """The reported four pages exist, in the reported order."""
    pages = bot.build_help_pages()
    assert len(pages) == 4
    assert [page.title for page in pages] == [
        "🌱 Epiphyte",
        "Commands",
        "On Its Own Time",
        "Persistence & Permanence",
    ]


def test_help_view_button_states_at_boundaries() -> None:
    """Previous is disabled on the first page, Next on the last."""
    pages = bot.build_help_pages()
    view = bot.HelpView(pages, author_id=1)
    assert view.previous_page.disabled is True
    assert view.next_page.disabled is False

    view._index = len(pages) - 1
    view._update_buttons()
    assert view.previous_page.disabled is False
    assert view.next_page.disabled is True


def test_help_view_interaction_check_rejects_other_user() -> None:
    """Someone other than the original invoker is rejected, politely."""
    pages = bot.build_help_pages()
    view = bot.HelpView(pages, author_id=1)
    interaction = _make_interaction(user_id=2)

    allowed = asyncio.run(view.interaction_check(interaction))

    assert allowed is False
    interaction.response.send_message.assert_awaited_once()
