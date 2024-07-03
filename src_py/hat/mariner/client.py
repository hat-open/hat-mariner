from collections.abc import Collection
import asyncio
import contextlib
import itertools
import logging
import typing

from hat import aio
from hat.drivers import tcp
import hat.event.common

from hat.mariner import transport


mlog: logging.Logger = logging.getLogger(__name__)

StatusCb: typing.TypeAlias = aio.AsyncCallable[
    ['Connection', hat.event.common.Status],
    None]

EventsCb: typing.TypeAlias = aio.AsyncCallable[
    ['Connection', Collection[hat.event.common.Event]],
    None]


async def connect(addr: tcp.Address,
                  client_name: str,
                  *,
                  client_token: str | None = None,
                  subscriptions: Collection[hat.event.common.EventType] = [],
                  server_id: hat.event.common.ServerId | None = None,
                  persisted: bool = False,
                  ping_delay: float | None = 30,
                  ping_timeout: float = 30,
                  status_cb: StatusCb | None = None,
                  events_cb: EventsCb | None = None,
                  **kwargs
                  ) -> 'Connection':
    conn = Connection()
    conn._status_cb = status_cb
    conn._events_cb = events_cb
    conn._loop = asyncio.get_running_loop()
    conn._status = hat.event.common.Status.STANDBY
    conn._next_req_ids = itertools.count(1)
    conn._futures = {}
    conn._ping_event = asyncio.Event()

    conn._conn = await transport.connect(addr, **kwargs)

    try:
        init_req = transport.InitReqMsg(client_name=client_name,
                                        client_token=client_token,
                                        subscriptions=subscriptions,
                                        server_id=server_id,
                                        persisted=persisted)
        await conn._conn.send(init_req)

        init_res = await conn._conn.receive()
        if not isinstance(init_res, transport.InitResMsg):
            raise Exception('invalid initiate response')

        if not init_res.success:
            raise Exception('initiate error' if init_res.error is None
                            else f'initiate error: {init_res.error}')

        conn._status = init_res.status

        conn.async_group.spawn(conn._receive_loop)

        if ping_delay:
            conn.async_group.spawn(conn._ping_loop, ping_delay, ping_timeout)

    except BaseException:
        await aio.uncancellable(conn.async_close())
        raise

    return conn


class Connection(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._conn.async_group

    @property
    def status(self) -> hat.event.common.Status:
        return self._status

    async def register(self,
                       register_events: Collection[hat.event.common.RegisterEvent] # NOQA
                       ) -> Collection[hat.event.common.Event] | None:
        register_id = next(self._next_req_ids)
        req = transport.RegisterReqMsg(register_id=register_id,
                                       register_events=register_events)

        res = await self._send_req(req, register_id)
        if not isinstance(res, transport.RegisterResMsg):
            raise Exception('invalid register response')

        return res.events

    async def query(self,
                    params: hat.event.common.QueryParams
                    ) -> hat.event.common.QueryResult:
        query_id = next(self._next_req_ids)
        req = transport.QueryReqMsg(query_id=query_id,
                                    params=params)

        res = await self._send_req(req, query_id)
        if not isinstance(res, transport.QueryResMsg):
            raise Exception('invalid query response')

        return res.result

    async def _send_req(self, req, req_id):
        if not self.is_open:
            raise ConnectionError()

        future = self._loop.create_future()
        self._futures[req_id] = future

        try:
            await self._conn.send(req)

            if not self.is_open:
                raise ConnectionError()

            return await future

        finally:
            self._futures.pop(req_id)

    async def _receive_loop(self):
        try:
            while True:
                msg = await self._conn.receive()

                self._ping_event.set()

                if isinstance(msg, transport.StatusMsg):
                    self._status = msg.status

                    if self._status_cb:
                        await aio.call(self._status_cb, self, msg.status)

                elif isinstance(msg, transport.EventsMsg):
                    if self._events_cb:
                        await aio.call(self._events_cb, self, msg.events)

                elif isinstance(msg, transport.RegisterResMsg):
                    future = self._futures.get(msg.register_id)
                    if future and not future.done():
                        future.set_result(msg)

                elif isinstance(msg, transport.QueryResMsg):
                    future = self._futures.get(msg.query_id)
                    if future and not future.done():
                        future.set_result(msg)

                elif isinstance(msg, transport.PingResMsg):
                    pass

                else:
                    raise Exception('invalid message type')

        except ConnectionError:
            pass

        except Exception as e:
            mlog.error("receive loop error: %s", e, exc_info=e)

        finally:
            self.close()

            for future in self._futures.values():
                if not future.done():
                    future.set_exception(ConnectionError())

    async def _ping_loop(self, delay, timeout):
        try:
            while True:
                self._ping_event.clear()

                with contextlib.suppress(asyncio.TimeoutError):
                    await aio.wait_for(self._ping_event.wait(), delay)
                    continue

                req_id = next(self._next_req_ids)
                req = transport.PingReqMsg(req_id)
                await self._conn.send(req)

                with contextlib.suppress(asyncio.TimeoutError):
                    await aio.wait_for(self._ping_event.wait(), timeout)
                    continue

                mlog.debug("ping timeout")
                break

        except ConnectionError:
            pass

        finally:
            self.close()
