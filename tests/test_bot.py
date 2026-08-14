"""Tests for the Discord-adapter hardening added after Phase 9.

Covers channel-unreachable tracking, the germination confirmation gate, help
pagination, the two faces of ``/plant`` and the accuracy of what ``/help``
claims — all in ``bot.py``, which is otherwise untested since it is
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
import dataclasses
import inspect
import io
import re
import time
from unittest.mock import AsyncMock, MagicMock, call

import discord

import bot
import moisture
import presentation
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


def _make_guild(guild_id: int) -> MagicMock:
    """A fake guild with just the id the command-sync helpers read."""
    guild = MagicMock()
    guild.id = guild_id
    return guild


def _make_interaction(
    guild_id: int | None = 1,
    user_id: int = 42,
    permissions: discord.Permissions | None = None,
) -> MagicMock:
    """A fake interaction with awaitable response methods, matching what
    ``require_guild``, the commands and the views under test actually call.

    Defaults ``permissions`` to full permissions, so tests that predate the
    Manage Channels gate on ``/epiphyte-channel`` (see
    ``require_manage_channels``) and aren't about permissions at all don't
    need to think about it; tests of that gate pass their own.
    """
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.permissions = permissions if permissions is not None else discord.Permissions.all()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())
    return interaction


def _forbidden() -> discord.Forbidden:
    """A discord.Forbidden as raised when the bot can see a channel but can't post in it."""
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Access")


def _http_exception() -> discord.HTTPException:
    """A generic, non-Forbidden HTTPException (e.g. a transient server error)."""
    return discord.HTTPException(MagicMock(status=500, reason="Internal Server Error"), "boom")


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


def test_refresh_marks_unreachable_on_forbidden_send() -> None:
    """A discord.Forbidden while posting a fresh message marks it unreachable too.

    The channel resolves fine (unlike the "channel is gone" tests above) — it's
    the send itself that the bot isn't allowed to do.
    """
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, message_id=None)
    fake_channel = _make_channel(channel_id=100)
    fake_channel.send = AsyncMock(side_effect=_forbidden())
    client._text_channel = AsyncMock(return_value=fake_channel)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is not None


def test_refresh_marks_unreachable_on_forbidden_edit() -> None:
    """A discord.Forbidden while editing the existing message marks it unreachable too."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, message_id=500)
    fake_partial = MagicMock()
    fake_partial.edit = AsyncMock(side_effect=_forbidden())
    fake_channel = _make_channel(channel_id=100)
    fake_channel.get_partial_message = MagicMock(return_value=fake_partial)
    client._text_channel = AsyncMock(return_value=fake_channel)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is not None


def test_refresh_does_not_mark_unreachable_on_generic_http_exception() -> None:
    """A non-Forbidden HTTPException (e.g. a transient server error) is only logged.

    Only the specific Forbidden case is a standing "can't post here" condition;
    other HTTP failures stay exactly as before this change — logged, not surfaced.
    """
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, message_id=None)
    fake_channel = _make_channel(channel_id=100)
    fake_channel.send = AsyncMock(side_effect=_http_exception())
    client._text_channel = AsyncMock(return_value=fake_channel)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    asyncio.run(client.refresh_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is None


def test_reanchor_marks_unreachable_on_forbidden_send() -> None:
    """reanchor_channel_message surfaces a Forbidden send the same way refresh does."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, message_id=None)
    fake_channel = _make_channel(channel_id=100)
    fake_channel.send = AsyncMock(side_effect=_forbidden())
    client._text_channel = AsyncMock(return_value=fake_channel)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    asyncio.run(client.reanchor_channel_message(guild_id))

    assert client._states[guild_id].channel_unreachable_since is not None


def test_channel_trouble_message_reports_missing_channel_when_unresolvable() -> None:
    """If the channel no longer resolves at all, /plant is told it's gone."""
    client = bot.EpiphyteClient()
    client._text_channel = AsyncMock(return_value=None)

    message = asyncio.run(client._channel_trouble_message(channel_id=100))

    assert "isn't there anymore" in message
    assert "epiphyte-channel" in message


def test_channel_trouble_message_reports_permission_when_channel_resolves() -> None:
    """If the channel still resolves, /plant points at a permission problem instead."""
    client = bot.EpiphyteClient()
    client._text_channel = AsyncMock(return_value=_make_channel(channel_id=100))

    message = asyncio.run(client._channel_trouble_message(channel_id=100))

    assert "Send Messages" in message
    assert "isn't there anymore" not in message


def test_plant_command_shows_unreachable_note_when_channel_is_gone(monkeypatch) -> None:
    """/plant shows the "channel is gone" wording when it no longer resolves at all."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(
        guild_id=guild_id, message_id=500, channel_unreachable_since=999.0
    )
    client._text_channel = AsyncMock(return_value=None)
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs["content"] is not None
    assert "isn't there anymore" in kwargs["content"]
    assert "epiphyte-channel" in kwargs["content"]


def test_plant_command_shows_permission_note_when_channel_resolves(monkeypatch) -> None:
    """/plant shows the permission wording when the channel resolves but can't be posted to."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(
        guild_id=guild_id, message_id=500, channel_unreachable_since=999.0
    )
    client._text_channel = AsyncMock(return_value=_make_channel(channel_id=100))
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs["content"] is not None
    assert "Send Messages" in kwargs["content"]
    assert "isn't there anymore" not in kwargs["content"]


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


def test_germinate_plant_ignores_second_call_for_already_seeded_guild() -> None:
    """A second germinate_plant call for a guild that already has a plant is a no-op.

    Mirrors two ConfirmGerminationView confirmations racing for the same guild:
    the first call creates the plant, and a second one — however it is
    triggered — must not reset it back to a fresh seed and generation 1.
    """
    client = bot.EpiphyteClient()
    guild_id = 42

    first = asyncio.run(client.germinate_plant(guild_id, channel_id=100, now=1000.0))
    state_after_first = client._states[guild_id]

    second = asyncio.run(client.germinate_plant(guild_id, channel_id=200, now=2000.0))
    state_after_second = client._states[guild_id]

    assert first is True
    assert second is False
    assert state_after_second.structure.seed == state_after_first.structure.seed
    assert state_after_second.structure.generation == state_after_first.structure.generation == 1
    assert state_after_second.channel_id == state_after_first.channel_id == 100
    assert state_after_second.last_update == state_after_first.last_update == 1000.0


def test_germinate_plant_succeeds_normally_when_no_plant_exists() -> None:
    """The regular, single-confirmation case is unchanged: it still germinates."""
    client = bot.EpiphyteClient()
    guild_id = 9

    planted = asyncio.run(client.germinate_plant(guild_id, channel_id=100, now=1000.0))

    assert planted is True
    assert guild_id in client._states
    assert client._states[guild_id].channel_id == 100
    assert client._states[guild_id].structure.generation == 1


def test_second_confirmation_dialog_does_not_reset_the_plant(monkeypatch) -> None:
    """Two confirmation dialogs racing for the same guild: the second is a no-op.

    Simulates two people running ``/epiphyte-channel`` moments apart, both
    before either has confirmed — each gets their own view. The first
    confirmation germinates the plant; the second, confirmed afterwards, must
    see the plant already there and leave it untouched instead of silently
    reseeding it with a new seed and generation 1.
    """
    client = bot.EpiphyteClient()
    client.refresh_channel_message = AsyncMock()
    monkeypatch.setattr(bot, "client", client)

    guild_id = 77
    channel_a = _make_channel(channel_id=10)
    channel_b = _make_channel(channel_id=20)
    view_a = bot.ConfirmGerminationView(guild_id, channel_a, author_id=1)
    view_b = bot.ConfirmGerminationView(guild_id, channel_b, author_id=2)
    interaction_a = _make_interaction(guild_id=guild_id, user_id=1)
    interaction_b = _make_interaction(guild_id=guild_id, user_id=2)

    asyncio.run(view_a.confirm.callback(interaction_a))
    state_after_first = client._states[guild_id]

    asyncio.run(view_b.confirm.callback(interaction_b))
    state_after_second = client._states[guild_id]

    # The plant the first confirmation created survives untouched.
    assert state_after_second.structure.seed == state_after_first.structure.seed
    assert state_after_second.structure.generation == 1
    assert state_after_second.channel_id == channel_a.id

    # The first dialog reports the normal success message.
    first_kwargs = interaction_a.response.edit_message.await_args.kwargs
    assert channel_a.mention in first_kwargs["content"]

    # The second dialog is told plainly that it no longer applies.
    second_kwargs = interaction_b.response.edit_message.await_args.kwargs
    assert "already has a plant" in second_kwargs["content"]
    assert second_kwargs["view"] is None

    # Only the successful confirmation re-anchors the living message.
    client.refresh_channel_message.assert_awaited_once_with(guild_id)


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


# --- 2d: Manage Channels gating on /epiphyte-channel -------------------------


def test_require_manage_channels_allows_manage_channels_permission() -> None:
    """A member with Manage Channels passes, and nothing is sent."""
    interaction = _make_interaction(permissions=discord.Permissions(manage_channels=True))

    allowed = asyncio.run(bot.require_manage_channels(interaction))

    assert allowed is True
    interaction.response.send_message.assert_not_awaited()


def test_require_manage_channels_allows_administrator_permission() -> None:
    """A member with Administrator (but not Manage Channels itself) also passes."""
    interaction = _make_interaction(permissions=discord.Permissions(administrator=True))

    allowed = asyncio.run(bot.require_manage_channels(interaction))

    assert allowed is True
    interaction.response.send_message.assert_not_awaited()


def test_require_manage_channels_rejects_ordinary_member() -> None:
    """A member with neither permission is refused with a clear, ephemeral reason."""
    interaction = _make_interaction(permissions=discord.Permissions.none())

    allowed = asyncio.run(bot.require_manage_channels(interaction))

    assert allowed is False
    call = interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert "Manage Channels" in call.args[0]


def test_epiphyte_channel_rejects_rebind_without_manage_channels(monkeypatch) -> None:
    """Without the permission, rebinding an existing plant is refused and changes nothing."""
    client = bot.EpiphyteClient()
    guild_id = 5
    client._states[guild_id] = _make_state(guild_id=guild_id, channel_id=10, message_id=None)
    monkeypatch.setattr(bot, "client", client)

    interaction = _make_interaction(
        guild_id=guild_id, user_id=1, permissions=discord.Permissions.none()
    )
    channel = _make_channel(channel_id=20)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    call = interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert "Manage Channels" in call.args[0]
    assert "view" not in call.kwargs
    # The existing binding is untouched.
    assert client._states[guild_id].channel_id == 10


def test_epiphyte_channel_rejects_first_binding_without_manage_channels(monkeypatch) -> None:
    """The same refusal applies to a guild's very first binding, not just a rebind."""
    client = bot.EpiphyteClient()
    client.germinate_plant = AsyncMock()
    monkeypatch.setattr(bot, "client", client)

    guild_id = 8
    interaction = _make_interaction(
        guild_id=guild_id, user_id=1, permissions=discord.Permissions.none()
    )
    channel = _make_channel(channel_id=30)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    client.germinate_plant.assert_not_awaited()
    assert guild_id not in client._states
    call = interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert "view" not in call.kwargs


def test_epiphyte_channel_allows_rebind_with_manage_channels(monkeypatch) -> None:
    """With Manage Channels, rebinding an existing plant proceeds exactly as before."""
    client = bot.EpiphyteClient()
    guild_id = 6
    client._states[guild_id] = _make_state(guild_id=guild_id, channel_id=10, message_id=None)
    client.refresh_channel_message = AsyncMock()
    monkeypatch.setattr(bot, "client", client)

    interaction = _make_interaction(
        guild_id=guild_id, user_id=1, permissions=discord.Permissions(manage_channels=True)
    )
    channel = _make_channel(channel_id=20)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    assert client._states[guild_id].channel_id == 20
    assert "view" not in interaction.response.send_message.call_args.kwargs


def test_epiphyte_channel_allows_first_binding_with_administrator(monkeypatch) -> None:
    """Administrator alone (no explicit Manage Channels bit) also allows first binding."""
    client = bot.EpiphyteClient()
    monkeypatch.setattr(bot, "client", client)

    guild_id = 11
    interaction = _make_interaction(
        guild_id=guild_id, user_id=1, permissions=discord.Permissions(administrator=True)
    )
    channel = _make_channel(channel_id=40)

    asyncio.run(bot.epiphyte_channel.callback(interaction, channel))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    assert isinstance(kwargs["view"], bot.ConfirmGerminationView)


# --- 2c: help pagination -----------------------------------------------------


def test_help_pages_count_and_titles() -> None:
    """The reported five pages exist, in the reported order.

    The order is the argument: what Epiphyte *is*, then what it reads, then the
    three commands, then what arrives on its own, then what is permanent.
    """
    pages = bot.build_help_pages()
    assert len(pages) == 5
    assert [page.title for page in pages] == [
        "🌱 Epiphyte",
        "What It Reads",
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


# --- 4: voice sessions (Phase 17) -------------------------------------------
#
# The adapter half of voice activity: which stretches of time get credited to
# whom. The rules themselves are pure and tested in test_voice_activity.py; what
# is genuinely risky here is the bookkeeping around them — that a channel is
# settled *before* its membership changes, so each stretch is judged at the
# headcount that actually held during it, and that mute/deafen/AFK transitions
# take somebody out of the room as decisively as leaving it does.


def _voice_client(guild_id: int = 1) -> bot.EpiphyteClient:
    """A client with one germinated guild and nothing persisted."""
    client = bot.EpiphyteClient()
    client._states[guild_id] = _make_state(guild_id=guild_id)
    return client


def _member(user_id: int, guild_id: int = 1, afk_channel_id: int | None = None) -> MagicMock:
    """A fake member carrying just the guild attributes the handler reads."""
    member = MagicMock()
    member.bot = False
    member.id = user_id
    member.guild.id = guild_id
    member.guild.afk_channel = MagicMock(id=afk_channel_id) if afk_channel_id else None
    return member


def _voice_state(channel_id: int | None, muted: bool = False, deafened: bool = False) -> MagicMock:
    """A fake voice state: in ``channel_id`` (or nowhere), optionally silenced."""
    state = MagicMock()
    state.channel = MagicMock(id=channel_id) if channel_id is not None else None
    state.mute = False
    state.self_mute = muted
    state.deaf = False
    state.self_deaf = deafened
    return state


def _weights(client: bot.EpiphyteClient, guild_id: int = 1) -> dict[int, float]:
    return {user: round(weight, 4) for user, (weight, _) in client._voice_presence.get(guild_id, {}).items()}


def test_sitting_alone_in_a_voice_channel_earns_nothing(monkeypatch) -> None:
    """The headline claim, exercised through the actual event handler rather
    than the pure rule: someone joins, stays audible for eight hours, and no
    presence weight is ever created for them."""
    client = _voice_client()
    monkeypatch.setattr(bot.time, "time", lambda: 1000.0)
    asyncio.run(client.on_voice_state_update(_member(11), _voice_state(None), _voice_state(500)))

    asyncio.run(client._settle_open_voice_sessions(1000.0 + 8 * 60 * 60))

    assert client._voice_presence == {}
    assert client._voice_activity(1, 1000.0 + 8 * 60 * 60) == 0.0


def test_two_audible_people_both_accrue_from_the_moment_the_second_arrives(monkeypatch) -> None:
    """The first person's solo hour is worth nothing and the shared hour is worth
    the same to both — which only holds if the channel is settled before the
    second person is added to it."""
    client = _voice_client()
    monkeypatch.setattr(bot.time, "time", lambda: 0.0)
    asyncio.run(client.on_voice_state_update(_member(11), _voice_state(None), _voice_state(500)))
    monkeypatch.setattr(bot.time, "time", lambda: 3600.0)
    asyncio.run(client.on_voice_state_update(_member(12), _voice_state(None), _voice_state(500)))

    asyncio.run(client._settle_open_voice_sessions(7200.0))

    weights = _weights(client)
    assert set(weights) == {11, 12}
    assert weights[11] == weights[12] > 0.0


def test_muting_stops_the_clock_for_the_whole_room(monkeypatch) -> None:
    """Once one of two people mutes, the room is below the audible minimum, so
    neither of them accrues anything further however long they stay."""
    client = _voice_client()
    monkeypatch.setattr(bot.time, "time", lambda: 0.0)
    asyncio.run(client.on_voice_state_update(_member(11), _voice_state(None), _voice_state(500)))
    asyncio.run(client.on_voice_state_update(_member(12), _voice_state(None), _voice_state(500)))
    monkeypatch.setattr(bot.time, "time", lambda: 3600.0)
    asyncio.run(client._settle_open_voice_sessions(3600.0))
    earned = _weights(client)

    asyncio.run(
        client.on_voice_state_update(_member(12), _voice_state(500), _voice_state(500, muted=True))
    )
    asyncio.run(client._settle_open_voice_sessions(3600.0 + 6 * 60 * 60))

    assert _weights(client) == earned


def test_the_afk_channel_is_not_a_room_at_all(monkeypatch) -> None:
    """Two people parked in the guild's designated AFK channel never open a
    session there, so no amount of time in it can count."""
    client = _voice_client()
    monkeypatch.setattr(bot.time, "time", lambda: 0.0)
    for user_id in (11, 12):
        asyncio.run(
            client.on_voice_state_update(
                _member(user_id, afk_channel_id=999), _voice_state(None), _voice_state(999)
            )
        )

    asyncio.run(client._settle_open_voice_sessions(24 * 60 * 60))

    assert client._voice_sessions.get(1, {}) == {}
    assert client._voice_presence == {}


def test_a_rebirth_leaves_the_successor_unrooted() -> None:
    """Voice presence is wiped with the other two presence tables when a
    successor germinates — a new plant grows its own roots (see storage.py's
    module docstring for why this differs from the daily/thread tables)."""
    client = _voice_client()
    client._voice_presence[1] = {11: (0.9, 0.0), 12: (0.9, 0.0)}
    client._voice_sessions[1] = {500: bot.VoiceSession(audible={11, 12}, since=0.0)}
    client._voice_seconds[(1, 11)] = 400.0
    client._voice_windows[(1, 11)] = bot.WateringWindow(0.0, 3)

    asyncio.run(client._clear_voice_presence(1))

    assert client._voice_activity(1, 0.0) == 0.0
    assert 1 not in client._voice_sessions
    assert not client._voice_seconds and not client._voice_windows


# --- 5: set_channel serialized against an in-flight refresh (adversarial
# consolidation pass, Phase 18) -----------------------------------------------
#
# refresh_channel_message's final write only patches message_id onto whatever
# state is current at that moment, trusting channel_id to already be right.
# Found by simulating a moderator rebinding the guild's channel while the
# metabolic tick is mid-flight, still awaiting Discord's response to a post in
# the *old* channel: without set_channel holding the same per-guild message
# lock refresh_channel_message and reanchor_channel_message already hold, the
# tick's delayed write can land after the rebind and pair the *new*
# channel_id with a message_id that was actually posted to the *old* channel
# — an orphaned message left behind, and a state that self-heals only on the
# next tick's discord.NotFound. This reproduces that interleaving directly
# (rather than asserting on a timing coincidence) and checks the invariant
# the fix restores: message_id, whenever set, always names a message that was
# posted to the channel currently recorded as channel_id.


def test_rebind_racing_an_in_flight_refresh_does_not_mismatch_channel_and_message() -> None:
    """A rebind that lands while a tick's post to the old channel is still in
    flight must never leave the new channel_id paired with the old message."""
    client = bot.EpiphyteClient()
    guild_id = 1
    old_channel_id, new_channel_id = 100, 200
    client._states[guild_id] = _make_state(guild_id=guild_id, channel_id=old_channel_id)
    client._render_bytes = AsyncMock(return_value=b"fake-png")

    send_gate = asyncio.Event()
    old_message = MagicMock()
    old_message.id = 999

    async def _delayed_send(*_args, **_kwargs) -> MagicMock:
        await send_gate.wait()  # simulate the in-flight Discord network call
        return old_message

    old_channel = _make_channel(channel_id=old_channel_id)
    old_channel.send = AsyncMock(side_effect=_delayed_send)
    new_channel = _make_channel(channel_id=new_channel_id)

    async def _resolve(channel_id: int) -> MagicMock:
        return old_channel if channel_id == old_channel_id else new_channel

    client._text_channel = AsyncMock(side_effect=_resolve)

    async def scenario() -> None:
        refresh_task = asyncio.create_task(client.refresh_channel_message(guild_id))
        await asyncio.sleep(0)  # let it block inside old_channel.send()

        # Fired concurrently, not awaited inline: set_channel now waits on the
        # same lock refresh_channel_message holds for its whole body.
        rebind_task = asyncio.create_task(client.set_channel(guild_id, new_channel_id))
        await asyncio.sleep(0)

        send_gate.set()  # let the delayed post resolve
        await refresh_task
        await rebind_task

    asyncio.run(scenario())

    final = client._states[guild_id]
    assert final.channel_id == new_channel_id
    # message_id 999 was posted to old_channel_id; it must never be paired
    # with new_channel_id — either it is cleared (the rebind ran after the
    # tick's write and correctly wiped it) or, if seen before the rebind,
    # message_id would still correctly refer to the old channel. Both are
    # fine; the one forbidden outcome is exactly the one this test pins down.
    assert not (final.channel_id == new_channel_id and final.message_id == old_message.id)


# --- 6: a watering racing the metabolic tick's own state read (adversarial
# consolidation pass, Phase 18) ------------------------------------------------
#
# advance_life reads its guild's state once at the top, then awaits several
# lookups (breadth, rhythm, reaction warmth, thread depth, the voice-presence
# prune) before its final store. Every one of those is real I/O
# (asyncio.to_thread against SQLite), so a message's watering — itself
# atomic, since water_plant reads-then-stores with no await in between, see
# _store's docstring — can land in that window. Storing the moisture computed
# from the stale pre-watering snapshot on top of it would silently discard
# the watering; this pins down that the tick instead folds it in.


def test_a_watering_that_lands_mid_tick_is_not_silently_dropped(monkeypatch) -> None:
    """A message arriving while advance_life awaits its internal lookups must
    still show up in the moisture the tick finally stores."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now0 = 1_000_000.0
    client._states[guild_id] = storage.GuildState(
        guild_id=guild_id, structure=structure.germinate(seed=1),
        moisture=0.5, last_update=now0, channel_id=100, message_id=None,
    )
    monkeypatch.setattr(bot.time, "time", lambda: now0 + 10)

    real_guild_rhythm = client._guild_rhythm

    async def _slow_guild_rhythm(guild_id: int, now: float) -> float:
        await asyncio.sleep(0)  # yields control -- a message can land here
        return await real_guild_rhythm(guild_id, now)

    client._guild_rhythm = _slow_guild_rhythm

    async def scenario() -> None:
        tick_task = asyncio.create_task(client.advance_life(guild_id, now0 + 10))
        await asyncio.sleep(0)  # let the tick get into its awaited lookups
        await client.water_plant(guild_id, user_id=42, now=now0 + 10)
        await tick_task

    asyncio.run(scenario())

    final = client._states[guild_id]
    decay_only = moisture.decay(0.5, 10.0)
    assert final.moisture > decay_only, (
        "the concurrent watering must be reflected in the tick's final store, "
        "not overwritten by a value computed before it landed"
    )


# --- 7: reaction windows never swept (final pre-deployment stress test) ------
#
# _prune_watering_windows exists precisely so a (guild, person) pair that
# watered or voice-credited once, long ago, does not sit in memory for the
# bot's entire uptime -- it sweeps self._windows and self._voice_windows every
# tick. self._reaction_windows is the same kind of per-person diminishing-
# returns bookkeeping (see _water_reactor_presence, which mirrors
# _water_author_presence and _water_voice_presence exactly), but was missing
# from that sweep: every distinct (guild, reactor) pair that has ever reacted
# a single non-self reaction stayed in memory forever, unlike its two
# siblings. Over the lifetime of a long-running bot serving many guilds, that
# is unbounded memory growth from ordinary use, not just malicious flooding.


def test_prune_watering_windows_sweeps_reaction_windows_too() -> None:
    """A long-elapsed reaction window must be dropped exactly like its message
    and voice siblings are -- reaction presence is not a special case."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now = 0.0
    for person_id in range(50):
        client._windows[(guild_id, person_id)] = bot.WateringWindow(now, 1)
        client._voice_windows[(guild_id, person_id)] = bot.WateringWindow(now, 1)
        client._reaction_windows[(guild_id, person_id)] = bot.WateringWindow(now, 1)

    long_after = now + moisture.WATERING_WINDOW_SECONDS * 10
    client._prune_watering_windows(long_after)

    assert client._windows == {}
    assert client._voice_windows == {}
    assert client._reaction_windows == {}, (
        "reaction windows must be swept once their window has fully elapsed, "
        "exactly like message and voice windows -- otherwise every distinct "
        "reactor a guild has ever seen stays in memory for the bot's entire "
        "uptime"
    )


# --- 8: the ambient message shows the plant and nothing else -----------------
#
# The living channel message is the one surface nobody opted into: it is
# rebuilt every heartbeat and sits in a channel people are using for something
# else. The tests below hold it to carrying a full-size picture and the plant's
# own words, on every life event without exception -- checked here rather than
# only in test_presentation.py because it is the poured Discord embed, not the
# Panel, that a server actually sees.


def _grown(nodes: int, dead: int = 0) -> structure.Structure:
    """A structure with ``nodes`` nodes, the first ``dead`` of them dead wood.

    Fabricated rather than grown, mirroring ``tests/test_presentation.py``'s
    helper: every field the frame reads is set directly, so a 300-node plant in
    a drought costs a comprehension instead of weeks of simulated ticks.
    """
    base = structure.germinate(seed=12345)
    body = tuple(
        dataclasses.replace(
            base.nodes[0],
            id=index,
            parent_id=index - 1 if index else None,
            state=structure.NodeState.DEAD if index < dead else base.nodes[0].state,
        )
        for index in range(nodes)
    )
    return dataclasses.replace(
        base,
        nodes=body,
        step_count=900,
        active_tips=tuple(n.id for n in body if n.state is structure.NodeState.TIP),
    )


def _germinated(seed: int = 1, generation: int = 1) -> structure.Structure:
    """A just-germinated plant, optionally a successor rather than a founder."""
    return structure.germinate(seed=seed, generation=generation)


def test_the_ambient_embed_has_a_full_size_image_and_no_fields_on_every_event() -> None:
    """Every life event, as the poured embed rather than as the Panel.

    ``presentation`` decides this and is tested on it, but the pour is where a
    stray ``add_field`` or a thumbnail would actually reach a server, so the
    property is asserted again on the far side of it.
    """
    cases = {
        "germination": (_germinated(), 0.0),
        "rebirth": (_germinated(generation=4), 0.0),
        "dieback": (_grown(300, dead=60), 0.03),
        "drought": (_grown(300), 0.12),
        "thirst": (_grown(300), 0.30),
        "steady": (_grown(300), 0.50),
        "flourishing": (_grown(300), 0.90),
        "death": (_grown(300, dead=300), 0.0),
    }
    for name, (plant, moisture_value) in cases.items():
        embed = bot.build_plant_embed(moisture_value, plant)
        assert embed.fields == [], f"{name} carries instruments on the living message"
        assert embed.image.url == f"attachment://{bot.PLANT_IMAGE_FILENAME}", name
        assert embed.thumbnail.url is None, f"{name} shows the plant as a thumbnail"
        assert embed.description, f"{name} lost the plant's own words"
        # The accent system is untouched by the stripping: still state-derived.
        panel = presentation.compose(plant, moisture_value, bot.TICK_INTERVAL_SECONDS)
        assert embed.color == discord.Color(panel.accent), name


def test_the_cross_section_embed_keeps_its_row() -> None:
    """The single argued-for exception, on the far side of the pour too."""
    rings = (
        structure.Ring(year=2026, vitality=0.62, scarred=False),
        structure.Ring(year=2027, vitality=0.09, scarred=True),
    )
    embed = bot.build_plant_embed(0.12, _grown(300), rings)
    assert [field.name for field in embed.fields] == ["Rings", "Scar rings", "Moisture"]
    assert embed.image.url == f"attachment://{bot.PLANT_IMAGE_FILENAME}"


# --- 9: /plant's two faces ---------------------------------------------------


def _plant_view(monkeypatch, moisture_value: float = 0.5) -> bot.PlantSnapshotView:
    """Run ``/plant`` against a stubbed client and return the view it attached."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = storage.GuildState(
        guild_id=guild_id,
        structure=_grown(300),
        moisture=moisture_value,
        # Stamped now, so the display decay /plant applies is negligible and the
        # readings under test are the moisture that was actually passed in.
        last_update=time.time(),
        channel_id=100,
        message_id=500,
        channel_unreachable_since=None,
    )
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]
    return interaction.response.send_message.call_args.kwargs["view"]


def test_plant_opens_on_the_same_face_the_living_message_wears(monkeypatch) -> None:
    """The default view is the ambient one: full picture, no instruments."""
    client = bot.EpiphyteClient()
    guild_id = 1
    client._states[guild_id] = _make_state(guild_id=guild_id, message_id=500)
    monkeypatch.setattr(bot, "client", client)
    monkeypatch.setattr(render, "render", lambda *args, **kwargs: io.BytesIO(b"fake-png"))

    interaction = _make_interaction(guild_id=guild_id)
    asyncio.run(bot.plant.callback(interaction))  # pyright: ignore[reportCallIssue]

    kwargs = interaction.response.send_message.call_args.kwargs
    embed = kwargs["embed"]
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], bot.PlantSnapshotView)
    assert embed.fields == []
    assert embed.image.url == f"attachment://{bot.PLANT_IMAGE_FILENAME}"


def test_the_button_turns_the_reply_over_and_back(monkeypatch) -> None:
    """One toggle, two faces, and a label that always names what is *not* shown."""
    view = _plant_view(monkeypatch)
    assert view.toggle.label == bot.READINGS_LABEL

    interaction = _make_interaction()
    asyncio.run(view.toggle.callback(interaction))
    readings = interaction.response.edit_message.call_args.kwargs["embed"]
    assert view.toggle.label == bot.PLANT_LABEL
    assert [field.name for field in readings.fields][:4] == ["Moisture", "Stage", "Age", "Crown"]
    assert readings.thumbnail.url == f"attachment://{bot.PLANT_IMAGE_FILENAME}"
    assert readings.image.url is None

    back = _make_interaction()
    asyncio.run(view.toggle.callback(back))
    plant_face = back.response.edit_message.call_args.kwargs["embed"]
    assert view.toggle.label == bot.READINGS_LABEL
    assert plant_face.fields == []
    assert plant_face.image.url == f"attachment://{bot.PLANT_IMAGE_FILENAME}"


def test_the_readings_describe_the_same_instant_as_the_picture(monkeypatch) -> None:
    """Both faces are composed once, from one reading of the state.

    A readings panel recomputed on the button press would quietly disagree with
    the already-rendered picture beside it — the moisture decays continuously,
    so any later reading is a different moment.
    """
    view = _plant_view(monkeypatch, moisture_value=0.9)
    interaction = _make_interaction()
    asyncio.run(view.toggle.callback(interaction))
    readings = interaction.response.edit_message.call_args.kwargs["embed"]
    shown = next(field.value for field in readings.fields if field.name == "Moisture")
    assert shown == "90%"

    # Turning it back and forth must not move the number: it is a snapshot of one
    # instant, not a gauge that keeps reading while somebody stares at it.
    asyncio.run(view.toggle.callback(_make_interaction()))  # back to the plant
    again = _make_interaction()
    asyncio.run(view.toggle.callback(again))  # and over to the readings again
    repeat = again.response.edit_message.call_args.kwargs["embed"]
    assert next(f.value for f in repeat.fields if f.name == "Moisture") == shown


def test_two_invocations_do_not_share_button_state(monkeypatch) -> None:
    """Each /plant gets its own view bound to its own ephemeral reply.

    Nothing about the toggle is stored per guild or per person, so one person
    running the command twice — or two people running it seconds apart — cannot
    move each other's message or leak a half-turned state between them.
    """
    first = _plant_view(monkeypatch)
    second = _plant_view(monkeypatch)
    assert first is not second

    asyncio.run(first.toggle.callback(_make_interaction()))
    assert first.toggle.label == bot.PLANT_LABEL
    assert second.toggle.label == bot.READINGS_LABEL
    assert first.embed is not second.embed


def test_the_button_greys_itself_out_on_timeout() -> None:
    """An expired view disables its button in place rather than erroring later."""
    view = bot.PlantSnapshotView(discord.Embed(), discord.Embed(), author_id=1)
    view.message = MagicMock()
    view.message.edit = AsyncMock()

    asyncio.run(view.on_timeout())

    assert view.toggle.disabled is True
    view.message.edit.assert_awaited_once()
    assert view.message.edit.call_args.kwargs["view"] is view


def test_a_timed_out_view_survives_a_deleted_message() -> None:
    """A reply that is already gone must not raise out of the timeout handler."""
    view = bot.PlantSnapshotView(discord.Embed(), discord.Embed(), author_id=1)
    view.message = MagicMock()
    view.message.edit = AsyncMock(side_effect=_http_exception())

    asyncio.run(view.on_timeout())  # must not raise

    assert view.toggle.disabled is True


def test_plant_snapshot_view_interaction_check_rejects_other_user() -> None:
    """Someone other than the /plant invoker cannot toggle their ephemeral reply.

    Every other view bound to a per-user ephemeral response (HelpView,
    ConfirmGerminationView) restricts button presses to its own invoker; this
    view is the button behind /plant and must hold the same line, not rely
    solely on Discord's platform-level ephemeral-visibility guarantee.
    """
    view = bot.PlantSnapshotView(discord.Embed(), discord.Embed(), author_id=1)
    interaction = _make_interaction(user_id=2)

    allowed = asyncio.run(view.interaction_check(interaction))

    assert allowed is False
    interaction.response.send_message.assert_awaited_once()


def test_the_living_message_never_gets_a_view() -> None:
    """Buttons exist on /plant's ephemeral reply and nowhere else.

    The automatic channel message is the plant, full stop: no toggle, no
    instruments, nothing for anyone to press.
    """
    source = inspect.getsource(bot.EpiphyteClient.refresh_channel_message)
    source += inspect.getsource(bot.EpiphyteClient.reanchor_channel_message)
    assert "view=" not in source
    assert "build_instrument_embed" not in source


# --- 10: /help says only true things ----------------------------------------


def _help_text() -> str:
    """Every word of every /help page, as one string."""
    return "\n".join(page.description or "" for page in bot.build_help_pages())


def test_help_mentions_exactly_the_commands_that_exist() -> None:
    """No drift in either direction: nothing invented, nothing quietly omitted."""
    real = {command.name for command in bot.client.tree.get_commands()}
    mentioned = set(re.findall(r"`/([a-z-]+)", _help_text()))
    assert mentioned == real, f"help mentions {mentioned}, the tree has {real}"


def test_help_only_names_arguments_the_commands_actually_take() -> None:
    """``/epiphyte-channel <channel>`` has to match the real parameter name."""
    parameters = {
        command.name: {parameter.name for parameter in getattr(command, "parameters", [])}
        for command in bot.client.tree.get_commands()
    }
    for name, arguments in re.findall(r"`/([a-z-]+)([^`]*)`", _help_text()):
        for argument in re.findall(r"<([a-z_]+)>", arguments):
            assert argument in parameters[name], f"/{name} has no argument <{argument}>"


def test_help_cites_the_real_tick_interval_and_decay() -> None:
    """The stated durations are computed from the constants, not written down.

    Every number on these pages is derived at build time, so a recalibration of
    the growth interval or the decay half-life cannot leave the explanation
    quietly describing a bot that no longer exists.
    """
    text = _help_text()
    hours = bot.TICK_INTERVAL_SECONDS // 3600
    assert ("once an hour" if hours == 1 else f"once every {hours} hours") in text
    days = round(3 * moisture.DEFAULT_HALF_LIFE_SECONDS / (24 * 60 * 60))
    assert f"about {days} days of real quiet" in text


def test_help_describes_the_real_anti_farming_curve() -> None:
    """The window and the falloff are the ones ``moisture`` actually applies.

    Both are load-bearing claims — they are the whole reason the plant cannot be
    farmed — so neither may be an adjective standing in for a constant.
    """
    text = _help_text()
    assert "within a day" in text
    assert moisture.WATERING_WINDOW_SECONDS == 24 * 60 * 60, (
        "the watering window changed; /help still calls it a day"
    )
    assert "worth half of the one before it" in text
    assert moisture.WATERING_FALLOFF == 0.5, (
        "the falloff changed; /help still calls each further message half the last"
    )
    # And the claim itself, not just the constant behind it.
    assert moisture.effective_water_amount(1) == moisture.effective_water_amount(0) / 2


def test_help_states_how_long_the_wind_actually_lingers() -> None:
    """The one duration on the page that is seconds rather than days."""
    assert structure.WIND_LINGER_SECONDS == 90, (
        "the wind linger changed; /help still calls it a minute and a half"
    )
    assert "for a minute and a half after the last keystroke" in _help_text()
    assert structure.wind_is_stirring(seconds_since_typing=89) is True
    assert structure.wind_is_stirring(seconds_since_typing=91) is False


def test_help_describes_death_as_the_end_of_a_long_drought_not_a_deeper_one() -> None:
    """Death is every node dead, which a drought reaches by lasting, not by deepening."""
    assert "goes on long enough takes all of it" in _help_text()
    plant = _grown(50)
    assert structure.is_dead(plant) is False
    assert structure.is_dead(_grown(50, dead=50)) is True


def test_help_promises_only_readings_the_plant_actually_shows() -> None:
    """The instruments /help names on the button are the ones behind it."""
    text = _help_text()
    readings = presentation.compose_instruments(_grown(300), 0.9, bot.TICK_INTERVAL_SECONDS)
    values = {field.name.lower(): field.value.lower() for field in readings.fields}
    for promised in ("moisture", "stage", "age"):
        assert promised in text and promised in values
    assert "growing tips" in text and "growing tips" in values["crown"]


def test_help_claims_the_permission_gate_that_exists() -> None:
    """/help says /epiphyte-channel needs Manage Channels; it must be true."""
    assert "Manage Channels" in _help_text()

    denied = _make_interaction(permissions=discord.Permissions(send_messages=True))
    assert asyncio.run(bot.require_manage_channels(denied)) is False

    allowed = _make_interaction(permissions=discord.Permissions(manage_channels=True))
    assert asyncio.run(bot.require_manage_channels(allowed)) is True


def test_help_does_not_claim_a_reset_or_a_leaderboard() -> None:
    """Both are load-bearing promises on the persistence page, and both hold."""
    text = _help_text()
    assert "no delete command and no reset command" in text
    assert "no leaderboard" in text
    assert {c.name for c in bot.client.tree.get_commands()} == {"plant", "epiphyte-channel", "help"}


# --- Slash command sync: global registration only, one-time duplicate sweep ---
#
# The bug this guards against: an earlier fix gave every guild a permanent,
# guild-specific copy of every command (``copy_global_to`` + ``sync(guild=...)``
# from a since-removed ``on_guild_join`` handler and a since-removed startup
# backfill). Once this bot's ordinary global sync also reached one of those
# guilds, Discord showed every command twice. The fix is to stop creating
# guild-specific copies at all and, once, sweep every already-connected guild
# clean of whatever copy it still has — gated so the sweep can only ever fire
# once, a durable database flag rather than an in-memory one, since a
# container restart must not repeat it.


def test_no_guild_join_handler_creates_permanent_guild_commands() -> None:
    """There must be no ``on_guild_join`` handler at all: any such handler that
    calls ``copy_global_to`` + ``sync(guild=...)`` recreates the exact
    permanent, guild-specific copy this fix removes."""
    assert not hasattr(bot.EpiphyteClient, "on_guild_join")


def test_cleanup_clears_every_already_connected_guild_once(tmp_path) -> None:
    """On the first run after this fix ships, every guild already connected has
    its guild-specific command copy cleared and an empty guild sync pushed, so
    Discord drops whatever permanent copy it was still holding."""
    client = bot.EpiphyteClient()
    client._storage = storage.Storage(str(tmp_path / "sync.db"))
    guild_a, guild_b = _make_guild(1), _make_guild(2)
    client._connection = MagicMock(guilds=[guild_a, guild_b])
    client.tree.clear_commands = MagicMock()
    client.tree.sync = AsyncMock()

    asyncio.run(client._clear_guild_command_duplicates())

    assert client.tree.clear_commands.call_args_list == [call(guild=guild_a), call(guild=guild_b)]
    assert client.tree.sync.await_args_list == [call(guild=guild_a), call(guild=guild_b)]
    assert client._storage.guild_command_cleanup_done() is True
    client._storage.close()


def test_cleanup_never_touches_the_global_command_tree(tmp_path) -> None:
    """``clear_commands(guild=...)`` must only ever be called with a guild —
    never bare — since a bare call would wipe the global registration and take
    every command down everywhere, not just the guild-specific duplicate."""
    client = bot.EpiphyteClient()
    client._storage = storage.Storage(str(tmp_path / "sync.db"))
    client._connection = MagicMock(guilds=[_make_guild(1)])
    client.tree.clear_commands = MagicMock()
    client.tree.sync = AsyncMock()

    asyncio.run(client._clear_guild_command_duplicates())

    for call_args in client.tree.clear_commands.call_args_list:
        assert call_args.kwargs.get("guild") is not None
    client._storage.close()


def test_cleanup_never_runs_twice_even_across_a_restart(tmp_path) -> None:
    """The flag lives in the database, not just in memory, so a second process
    opening the same file — a container restart — does not sweep again. Left
    unguarded this would cost one Discord API call per connected guild on
    every restart, forever, for a migration that only ever needed to run once."""
    db_path = str(tmp_path / "sync.db")
    first = bot.EpiphyteClient()
    first._storage = storage.Storage(db_path)
    first._connection = MagicMock(guilds=[_make_guild(1)])
    first.tree.clear_commands = MagicMock()
    first.tree.sync = AsyncMock()
    asyncio.run(first._clear_guild_command_duplicates())
    first._storage.close()

    second = bot.EpiphyteClient()
    second._storage = storage.Storage(db_path)
    second._connection = MagicMock(guilds=[_make_guild(1)])
    second.tree.clear_commands = MagicMock()
    second.tree.sync = AsyncMock()
    asyncio.run(second._clear_guild_command_duplicates())

    second.tree.clear_commands.assert_not_called()
    second.tree.sync.assert_not_awaited()
    second._storage.close()


def test_cleanup_marks_done_even_when_one_guild_sync_fails(tmp_path) -> None:
    """A single guild's sync failing during the sweep must not leave the flag
    unset forever and turn a one-time migration into one that retries — and
    fails the same way — on every future restart."""
    client = bot.EpiphyteClient()
    client._storage = storage.Storage(str(tmp_path / "sync.db"))
    client._connection = MagicMock(guilds=[_make_guild(1), _make_guild(2)])
    client.tree.clear_commands = MagicMock()
    client.tree.sync = AsyncMock(side_effect=_http_exception())

    asyncio.run(client._clear_guild_command_duplicates())  # must not raise

    assert client._storage.guild_command_cleanup_done() is True
    client._storage.close()


# --- 11: thread-tracking is capped per guild (unbounded-growth regression) ---
#
# Every id _record_thread_activity keys its cache by is either a real Discord
# account (author_id -- costly for one attacker to multiply) or a thread id
# minted by on_thread_create for literally every thread created, qualifying or
# not. A single member with ordinary thread-creation permission could once
# grow self._thread_activity[guild_id] without bound just by opening threads
# in a loop, which also made _guild_thread_depth's once-a-tick aggregation
# scan an ever-larger dict directly on the event loop. MAX_TRACKED_THREADS_PER_GUILD
# closes that off: a guild already at the ceiling simply stops admitting new
# thread ids until staleness pruning frees room, while a thread already being
# tracked keeps updating normally.


def test_thread_tracking_stays_bounded_under_a_creation_flood() -> None:
    """Flooding a guild with far more new threads than the cap must not grow
    its cache past the cap -- this is the unbounded-memory-growth regression
    itself, reproduced directly against the flood scenario in the report."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now = 0.0

    for thread_id in range(bot.MAX_TRACKED_THREADS_PER_GUILD * 3):
        asyncio.run(
            client._record_thread_activity(guild_id, thread_id, thread_id, now, increment=False)
        )

    assert len(client._thread_activity[guild_id]) == bot.MAX_TRACKED_THREADS_PER_GUILD


def test_an_already_tracked_thread_keeps_updating_once_the_guild_is_at_the_cap() -> None:
    """The cap must refuse admission of *new* thread ids only -- a thread that
    was already being tracked before the ceiling was hit must go on recording
    real messages normally, exactly as if the guild were nowhere near it."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now = 0.0

    asyncio.run(client._record_thread_activity(guild_id, 0, 42, now, increment=False))
    for thread_id in range(1, bot.MAX_TRACKED_THREADS_PER_GUILD + 50):
        asyncio.run(
            client._record_thread_activity(guild_id, thread_id, thread_id, now, increment=False)
        )

    asyncio.run(client._record_thread_activity(guild_id, 0, 42, now + 1.0, increment=True))

    count, first_seen, last_seen = client._thread_activity[guild_id][0][42]
    assert count == 1, "a message in an already-tracked thread must still increment its count"
    assert first_seen == now
    assert last_seen == now + 1.0


def test_a_lone_flooder_cannot_evict_threads_other_people_actually_use() -> None:
    """Once at the cap, a flooder's further thread creations must be dropped
    outright -- not silently overwrite or evict a thread real conversations
    are already using -- so the cap is a refusal, not an eviction policy an
    attacker could exploit to push out genuine activity."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now = 0.0

    asyncio.run(client._record_thread_activity(guild_id, 999, 42, now, increment=False))
    for thread_id in range(bot.MAX_TRACKED_THREADS_PER_GUILD * 5):
        asyncio.run(
            client._record_thread_activity(guild_id, thread_id + 1000, thread_id, now, increment=False)
        )

    assert 999 in client._thread_activity[guild_id]
    assert len(client._thread_activity[guild_id]) == bot.MAX_TRACKED_THREADS_PER_GUILD


# --- 12: a presence write racing rebirth is serialized, not silently wiped ---
#
# advance_life's dead-plant branch stores the germinated successor -- making
# it the guild's current state synchronously, before its own await -- then
# separately, sequentially awaits four table clears and a VACUUM. Each of
# those clears is its own await point, so a concurrent on_message /
# on_raw_reaction_add / voice-state event for the *same* guild can write a
# fresh presence row for the new generation into that gap, which the
# not-yet-run clear then deletes moments later -- the table is keyed only by
# guild_id, never by generation, so whichever of the write and the clear runs
# last erases the other's effect. Reproduces the interleaving directly,
# mirroring test_rebind_racing_an_in_flight_refresh_does_not_mismatch_channel_and_message
# above (section 5) rather than asserting on a timing coincidence.


def _dead_structure(seed: int = 1) -> structure.Structure:
    """A structure whose only node is dead -- structure.is_dead() is True."""
    base = structure.germinate(seed=seed)
    return dataclasses.replace(
        base, nodes=(dataclasses.replace(base.nodes[0], state=structure.NodeState.DEAD),)
    )


def test_a_presence_write_racing_rebirth_lands_after_the_wipe_not_lost() -> None:
    """A presence write that fires while a successor is germinating must never
    be silently discarded by the not-yet-run clear behind it: it either lands
    before the clear (and is correctly wiped, belonging to the dying
    generation) or after (and survives, belonging to the new one). What must
    never happen is the old race -- written, then silently erased."""
    client = bot.EpiphyteClient()
    guild_id = 1
    now = 1_000_000.0
    client._states[guild_id] = storage.GuildState(
        guild_id=guild_id,
        structure=_dead_structure(),
        moisture=moisture.MIN_MOISTURE,
        last_update=now,
        channel_id=100,
        message_id=None,
        dead_ticks=bot.DEAD_PHASE_TICKS - 1,
    )
    client._author_presence[guild_id] = {999: (5.0, now)}  # the dying generation's own voice

    entered_clear = asyncio.Event()
    release_clear = asyncio.Event()
    original_clear = client._clear_author_presence

    async def _blocking_clear(guild_id: int) -> None:
        entered_clear.set()
        await release_clear.wait()  # simulate the in-flight clear taking a moment
        await original_clear(guild_id)

    client._clear_author_presence = _blocking_clear

    async def scenario() -> None:
        rebirth_task = asyncio.create_task(client.advance_life(guild_id, now))
        await entered_clear.wait()  # rebirth is inside its lock, past the store

        # Fired concurrently, not awaited inline: the water call now waits on
        # the same lock the rebirth sequence holds for its whole body.
        water_task = asyncio.create_task(client._water_author_presence(guild_id, 42, 1.0, now))
        await asyncio.sleep(0)
        # Must still be blocked -- the old bug let this write land right here,
        # in the gap between the successor's store and the clear still ahead.
        assert 42 not in client._author_presence.get(guild_id, {})

        release_clear.set()
        await rebirth_task
        await water_task

    asyncio.run(scenario())

    assert 999 not in client._author_presence[guild_id], (
        "the dying generation's own row must still be wiped"
    )
    assert 42 in client._author_presence[guild_id], (
        "a presence write racing the wipe must survive it, not be silently erased"
    )
