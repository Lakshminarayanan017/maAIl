"""The dependencies every handler resolves identity through.

There is exactly one path from an HTTP request to a database session that can
read user data, and it passes through ``authenticated``. That function is the
only place on the request path that sets ``app.user_id``.

It opens one session and one transaction. Identity resolution goes through
``app_resolve_session``, a SECURITY DEFINER function, because the lookup has
to happen before a tenant is known and RLS would otherwise return nothing.
The tenant is armed immediately afterwards, on the same connection, inside
the same transaction -- so by the time a handler body runs, every query it
can make is already scoped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SESSION_COOKIE, csrf_token_valid, hash_token
from app.core.tenancy import set_tenant
from app.database.engine import SessionFactory

_RESOLVE_SESSION = text("SELECT app_resolve_session(:token_hash)")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Cookie"},
)


@dataclass
class Auth:
    user_id: UUID
    session: AsyncSession


async def unscoped_session() -> AsyncIterator[AsyncSession]:
    """A session with no tenant armed.

    For endpoints that touch no user-scoped table, and for the sign-in flow,
    which runs before a tenant exists. A user-scoped read through this returns
    zero rows rather than every row, because ``app_current_user()`` is NULL --
    empty is the right failure mode.
    """
    async with SessionFactory() as session:
        yield session


UnscopedSession = Annotated[AsyncSession, Depends(unscoped_session)]


async def authenticated(request: Request) -> AsyncIterator[Auth]:
    """Resolve the session cookie and arm the tenant, or 401.

    Commits on success, rolls back on any exception.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _UNAUTHENTICATED

    async with SessionFactory() as session:
        async with session.begin():
            resolved = (
                await session.execute(_RESOLVE_SESSION, {"token_hash": hash_token(token)})
            ).scalar()
            if resolved is None:
                # Expired, revoked, or never existed. The caller learns which
                # it was by signing in again, not from this response.
                raise _UNAUTHENTICATED

            user_id = UUID(str(resolved))
            await set_tenant(session, user_id)
            request.state.user_id = user_id
            yield Auth(user_id=user_id, session=session)


AuthContext = Annotated[Auth, Depends(authenticated)]


async def current_user_id(auth: AuthContext) -> UUID:
    return auth.user_id


CurrentUserId = Annotated[UUID, Depends(current_user_id)]


async def tenant_session_dep(auth: AuthContext) -> AsyncSession:
    """A transaction scoped to the authenticated user.

    The same session ``authenticated`` opened: one connection per request, not
    one per dependency, because FastAPI caches a dependency within a request.
    """
    return auth.session


TenantSession = Annotated[AsyncSession, Depends(tenant_session_dep)]


async def require_csrf(request: Request) -> None:
    """Double-submit check on every mutation.

    SameSite=Lax already blocks a cross-site form post. This covers what it
    does not: a same-site subdomain, and a browser that treats Lax loosely.
    """
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if not csrf_token_valid(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid CSRF token",
        )


CsrfProtected = Depends(require_csrf)
