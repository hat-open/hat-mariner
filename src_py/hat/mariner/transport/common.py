from hat.mariner.common import *  # NOQA

from collections.abc import Collection
import typing

import hat.event.common


class InitReqMsg(typing.NamedTuple):
    client_name: str
    client_token: str | None
    subscriptions: Collection[hat.event.common.EventType]
    server_id: hat.event.common.ServerId | None
    persisted: bool


class InitResMsg(typing.NamedTuple):
    success: bool
    status: hat.event.common.Status | None
    error: str | None


class StatusMsg(typing.NamedTuple):
    status: hat.event.common.Status


class EventsMsg(typing.NamedTuple):
    events: Collection[hat.event.common.Event]


class RegisterReqMsg(typing.NamedTuple):
    register_id: int
    register_events: Collection[hat.event.common.RegisterEvent]


class RegisterResMsg(typing.NamedTuple):
    register_id: int
    success: bool
    events: Collection[hat.event.common.Event] | None


class QueryReqMsg(typing.NamedTuple):
    query_id: int
    params: hat.event.common.QueryParams


class QueryResMsg(typing.NamedTuple):
    query_id: int
    result: hat.event.common.QueryResult


class PingReqMsg(typing.NamedTuple):
    ping_id: int


class PingResMsg(typing.NamedTuple):
    ping_id: int


Msg: typing.TypeAlias = (InitReqMsg |
                         InitResMsg |
                         StatusMsg |
                         EventsMsg |
                         RegisterReqMsg |
                         RegisterResMsg |
                         QueryReqMsg |
                         QueryResMsg |
                         PingReqMsg |
                         PingResMsg)
