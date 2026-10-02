"""Paper-trading profiles: REST routes.

A profile is a named paper account with a starting balance of the user's choosing. It keeps its
balance, its history and its figures when a replay ends and when the program is restarted (see
``app/replay/profiles.py``). Every reply is the whole list, so a screen only has to show what it got.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.replay.profiles import ProfileError
from app.schemas import NewProfile, ProfilesView, RenameProfile, ResetProfile
from app.state import AppState, get_state

router = APIRouter(prefix="/api/replay/profiles", tags=["replay profiles"])


def _view(state: AppState) -> ProfilesView:
    return ProfilesView(active=state.profiles.active_id(), profiles=state.profiles.summaries())


def _follow(state: AppState) -> None:
    """A replay that is running trades on whichever profile is the active one now."""
    if state.replay is not None:
        state.replay.use_account(state.profiles.active())


def _fail(exc: ProfileError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("", response_model=ProfilesView)
def list_profiles() -> ProfilesView:
    return _view(get_state())


@router.post("", response_model=ProfilesView)
def create_profile(body: NewProfile) -> ProfilesView:
    state = get_state()
    try:
        state.profiles.create(body.name, body.balance, activate=body.activate)
    except ProfileError as exc:
        raise _fail(exc) from exc
    _follow(state)
    return _view(state)


@router.patch("/{profile_id}", response_model=ProfilesView)
def rename_profile(profile_id: str, body: RenameProfile) -> ProfilesView:
    state = get_state()
    try:
        state.profiles.rename(profile_id, body.name)
    except ProfileError as exc:
        raise _fail(exc) from exc
    return _view(state)


@router.post("/{profile_id}/select", response_model=ProfilesView)
def select_profile(profile_id: str) -> ProfilesView:
    state = get_state()
    try:
        state.profiles.set_active(profile_id)
    except ProfileError as exc:
        raise _fail(exc) from exc
    _follow(state)
    return _view(state)


@router.post("/{profile_id}/reset", response_model=ProfilesView)
def reset_profile(profile_id: str, body: ResetProfile | None = None) -> ProfilesView:
    """Begin the profile again: no positions, no history, the balance it began with (or ``balance``)."""
    state = get_state()
    try:
        engine = state.profiles.reset(profile_id, body.balance if body else None)
    except ProfileError as exc:
        raise _fail(exc) from exc
    replay = state.replay
    if replay is not None and replay.paper is engine and replay.bars:
        engine.restart_curve(replay.bars[min(replay.index, replay.total - 1)])  # the curve starts again here
    return _view(state)


@router.delete("/{profile_id}", response_model=ProfilesView)
def delete_profile(profile_id: str) -> ProfilesView:
    """Remove a profile and its history for good. Deleting the one in use switches to another."""
    state = get_state()
    try:
        state.profiles.delete(profile_id)
    except ProfileError as exc:
        raise _fail(exc) from exc
    _follow(state)
    return _view(state)
