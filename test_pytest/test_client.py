import asyncio

import pytest

from hat import aio
from hat import util
from hat.drivers import tcp
import hat.event.common

from hat.mariner import transport
import hat.mariner.client


events = [
    hat.event.common.Event(
        id=hat.event.common.EventId(1, 2, 3),
        type=('a', 'b', 'c'),
        timestamp=hat.event.common.now(),
        source_timestamp=None,
        payload=None),

    hat.event.common.Event(
        id=hat.event.common.EventId(3, 2, 1),
        type=('c', 'b', 'a'),
        timestamp=hat.event.common.now(),
        source_timestamp=hat.event.common.now(),
        payload=hat.event.common.EventPayloadJson(42)),

    hat.event.common.Event(
        id=hat.event.common.EventId(3, 2, 1),
        type=('c', 'b', 'a'),
        timestamp=hat.event.common.now(),
        source_timestamp=hat.event.common.now(),
        payload=hat.event.common.EventPayloadBinary(type='type',
                                                    data=b'data'))
]

register_events = [
    hat.event.common.RegisterEvent(
        type=('a', 'b', 'c'),
        source_timestamp=None,
        payload=None),

    hat.event.common.RegisterEvent(
        type=('c', 'b', 'a'),
        source_timestamp=hat.event.common.now(),
        payload=hat.event.common.EventPayloadJson(42)),

    hat.event.common.RegisterEvent(
        type=('c', 'b', 'a'),
        source_timestamp=hat.event.common.now(),
        payload=hat.event.common.EventPayloadBinary(type='type',
                                                    data=b'data'))
]

query_params = [
    hat.event.common.QueryLatestParams(),

    hat.event.common.QueryLatestParams(
        event_types=[('*',)]),

    hat.event.common.QueryTimeseriesParams(),

    hat.event.common.QueryTimeseriesParams(
        event_types=[('a', 'b', 'c')],
        t_from=hat.event.common.now(),
        t_to=hat.event.common.now(),
        source_t_from=hat.event.common.now(),
        source_t_to=hat.event.common.now(),
        order=hat.event.common.Order.ASCENDING,
        order_by=hat.event.common.OrderBy.SOURCE_TIMESTAMP,
        max_results=123,
        last_event_id=hat.event.common.EventId(1, 2, 3)),

    hat.event.common.QueryServerParams(
        server_id=123),

    hat.event.common.QueryServerParams(
        server_id=123,
        persisted=True,
        max_results=123,
        last_event_id=hat.event.common.EventId(1, 2, 3))
]


query_results = [
    hat.event.common.QueryResult(events=[],
                                 more_follows=False),

    hat.event.common.QueryResult(events=events,
                                 more_follows=True)
]


def assert_query_params_equal(params1, params2):

    def normalize(params):
        if (isinstance(params, (hat.event.common.QueryLatestParams,
                                hat.event.common.QueryTimeseriesParams)) and
                params.event_types is not None):
            return params._replace(event_types=list(params.event_types))

        return params

    assert normalize(params1) == normalize(params2)


def assert_query_result_equal(result1, result2):

    def normalize(result):
        return result._replace(events=list(result.events))

    assert normalize(result1) == normalize(result2)


@pytest.fixture
def addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


async def test_connect(addr):
    conn_queue = aio.Queue()
    client_name = 'client name'
    client_token = 'client token'
    subscriptions = [('a', 'b', 'c'), ('d', '*')]
    server_id = 123
    persisted = True

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=server_id,
        persisted=persisted))

    conn = await conn_queue.get()

    req = await conn.receive()
    assert isinstance(req, transport.InitReqMsg)
    assert req.client_name == client_name
    assert req.client_token == client_token
    assert list(req.subscriptions) == subscriptions
    assert req.server_id == server_id
    assert req.persisted == persisted

    assert not client_task.done()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.OPERATIONAL,
                               error=None)
    await conn.send(res)

    client = await client_task

    assert client.is_open
    assert conn.is_open

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


async def test_connect_error(addr):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name'))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=False,
                               status=None,
                               error='abc')
    await conn.send(res)

    with pytest.raises(Exception, match='.*abc.*'):
        await client_task

    await conn.wait_closed()
    await srv.async_close()


async def test_status(addr):
    conn_queue = aio.Queue()
    status_queue = aio.Queue()

    def on_status(client, status):
        status_queue.put_nowait(status)

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name',
        status_cb=on_status))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    assert client.status == hat.event.common.Status.STANDBY
    assert status_queue.empty()

    msg = transport.StatusMsg(status=hat.event.common.Status.OPERATIONAL)
    await conn.send(msg)

    status = await status_queue.get()
    assert status == hat.event.common.Status.OPERATIONAL
    assert client.status == hat.event.common.Status.OPERATIONAL
    assert status_queue.empty()

    msg = transport.StatusMsg(status=hat.event.common.Status.STANDBY)
    await conn.send(msg)

    status = await status_queue.get()
    assert status == hat.event.common.Status.STANDBY
    assert client.status == hat.event.common.Status.STANDBY
    assert status_queue.empty()

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


@pytest.mark.parametrize('events', [
    [],
    events
])
async def test_events(addr, events):
    conn_queue = aio.Queue()
    events_queue = aio.Queue()

    def on_events(client, events):
        events_queue.put_nowait(events)

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name',
        events_cb=on_events))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    msg = transport.EventsMsg(events=events)
    await conn.send(msg)

    received_events = await events_queue.get()
    assert list(received_events) == events
    assert events_queue.empty()

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


@pytest.mark.parametrize('register_events', [
    [],
    register_events
])
@pytest.mark.parametrize('events', [
    None,
    [],
    events
])
async def test_register(addr, register_events, events):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name'))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    register_task = asyncio.create_task(client.register(register_events))

    req = await conn.receive()
    assert isinstance(req, transport.RegisterReqMsg)
    assert list(req.register_events) == register_events

    assert not register_task.done()

    res = transport.RegisterResMsg(register_id=req.register_id,
                                   success=events is not None,
                                   events=events)
    await conn.send(res)

    result = await register_task

    if events is None:
        assert result is None

    else:
        assert list(result) == events

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


@pytest.mark.parametrize('params', query_params)
@pytest.mark.parametrize('result', query_results)
async def test_query(addr, params, result):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name'))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    register_task = asyncio.create_task(client.query(params))

    req = await conn.receive()
    assert isinstance(req, transport.QueryReqMsg)
    assert_query_params_equal(req.params, params)

    assert not register_task.done()

    res = transport.QueryResMsg(query_id=req.query_id,
                                result=result)
    await conn.send(res)

    query_result = await register_task

    assert_query_result_equal(query_result, result)

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


async def test_ping(addr):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name',
        ping_delay=0.01))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    for _ in range(3):
        req = await conn.receive()
        assert isinstance(req, transport.PingReqMsg)

        res = transport.PingResMsg(ping_id=req.ping_id)
        await conn.send(res)

    assert client.is_open
    assert conn.is_open

    await client.async_close()
    await conn.async_close()
    await srv.async_close()


async def test_ping_timeout(addr):
    conn_queue = aio.Queue()

    srv = await transport.listen(conn_queue.put_nowait, addr)

    client_task = asyncio.create_task(hat.mariner.client.connect(
        addr=addr,
        client_name='client name',
        ping_delay=0.01,
        ping_timeout=0.01))

    conn = await conn_queue.get()
    await conn.receive()

    res = transport.InitResMsg(success=True,
                               status=hat.event.common.Status.STANDBY,
                               error=None)
    await conn.send(res)

    client = await client_task

    req = await conn.receive()
    assert isinstance(req, transport.PingReqMsg)

    await client.wait_closed()
    await conn.wait_closed()

    await srv.async_close()
