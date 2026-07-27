"""Tests for the Discord-adapter hardening added after Phase 9.

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

import discord

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
