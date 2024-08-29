import asyncio

import pytest

from hat import aio
from hat import json
from hat import util
from hat.drivers import tcp
import hat.event.eventer
import hat.event.common

from hat.mariner import transport
import hat.mariner.server.server


@pytest.fixture
def mariner_addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


@pytest.fixture
def eventer_addr():
    return tcp.Address('127.0.0.1', util.get_unused_tcp_port())


@pytest.fixture
def conf(mariner_addr, eventer_addr):
    return {
        'name': 'name',
        'mariner': {
            'host': mariner_addr.host,
            'port': mariner_addr.port},
        'eventer': {
            'host': eventer_addr.host,
            'port': eventer_addr.port,
            'token': None},
        'clients': []}


async def test_create(conf):
    server = await hat.mariner.server.server.create_server(conf)

    assert isinstance(server, hat.mariner.server.server.Server)
    assert server.is_open

    server.close()
    await server.wait_closing()
    assert server.is_closing
    await server.wait_closed()
    assert server.is_closed


async def test_connect(conf, mariner_addr):
    server = await hat.mariner.server.server.create_server(conf)

    conn = await transport.connect(mariner_addr)

    with pytest.raises(asyncio.TimeoutError):
        await aio.wait_for(conn.receive(), timeout=0.05)

    assert conn.info.remote_addr == mariner_addr

    await server.async_close()

    assert conn.is_closed


@pytest.mark.parametrize('status', hat.event.common.Status)
@pytest.mark.parametrize('client_token', [None, 'a client token...'])
async def test_init_success(conf, mariner_addr, eventer_addr, status,
                            client_token):
    client_name = 'cli1'
    subscriptions = []

    clients = [{'name': client_name,
                'token': client_token,
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    eventer_server = await hat.event.eventer.listen(eventer_addr,
                                                    status=status)

    server = await hat.mariner.server.server.create_server(conf)

    conn = await transport.connect(mariner_addr)

    init_req = transport.InitReqMsg(
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=None,
        persisted=False)
    await conn.send(init_req)

    init_resp = await conn.receive()
    assert isinstance(init_resp, transport.InitResMsg)
    assert init_resp.success is True
    assert init_resp.status == status
    assert init_resp.error is None

    await server.async_close()
    await eventer_server.async_close()


@pytest.mark.parametrize('client_name, client_token, with_eventer, error', [
    ('unknown client', 'cli1 token', True, 'invalid client name'),
    ('cli1', 'wrong token', True, 'invalid client token'),
    ('cli1', 'cli1 token', False, 'error connecting to eventer server'),
    ])
async def test_init_failure(conf, mariner_addr, eventer_addr, client_name,
                            client_token, with_eventer, error):

    subscriptions = []
    server_id = None
    persisted = False

    clients = [{'name': 'cli1',
                'token': 'cli1 token',
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    if with_eventer:
        eventer_server = await hat.event.eventer.listen(eventer_addr)

    server = await hat.mariner.server.server.create_server(conf)

    conn = await transport.connect(mariner_addr)

    init_req = transport.InitReqMsg(
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=server_id,
        persisted=persisted)

    await conn.send(init_req)

    init_resp = await conn.receive()
    assert isinstance(init_resp, transport.InitResMsg)
    assert init_resp.success is False
    assert init_resp.status is None
    assert init_resp.error == error

    await conn.wait_closed()

    assert server.is_open

    await server.async_close()
    if with_eventer:
        await eventer_server.async_close()


async def test_eventer_connect(conf, mariner_addr, eventer_addr):
    clients_count = 10
    conn_info_queue = aio.Queue()

    def on_connection(conn_info):
        conn_info_queue.put_nowait(conn_info)

    init_msgs = [
        transport.InitReqMsg(
            client_name=f"cli{i}",
            client_token=f"cli{i} token",
            subscriptions=[(f'x{i}', f'y{i}'),
                           ('a', 'b', 'c')],
            server_id=i,
            persisted=bool(i % 2))
        for i in range(clients_count)]

    clients_conf = [{'name': i.client_name,
                     'token': i.client_token,
                     'subscriptions': [i.subscriptions[0],
                                       ('d', 'e', 'f')]}
                    for i in init_msgs]
    conf = json.set_(conf, 'clients', clients_conf)

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        connected_cb=on_connection,
        disconnected_cb=on_connection)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conns = set()
    eventer_conn_infos = set()

    for init_msg, client_conf in zip(init_msgs, clients_conf):
        mariner_conn = await transport.connect(mariner_addr)
        mariner_conns.add(mariner_conn)

        await mariner_conn.send(init_msg)

        init_resp = await mariner_conn.receive()
        assert init_resp.success
        assert init_resp.error is None

        eventer_conn_info = await conn_info_queue.get()
        eventer_conn_infos.add(eventer_conn_info)

        assert (eventer_conn_info.client_name ==
                f"mariner/{conf['name']}/{init_msg.client_name}")
        assert eventer_conn_info.client_token == conf['eventer']['token']
        assert (set(eventer_conn_info.subscription.get_query_types()) ==
                set(init_msg.subscriptions).intersection(
                    set(client_conf['subscriptions'])))
        assert eventer_conn_info.server_id == init_msg.server_id
        assert eventer_conn_info.persisted == init_msg.persisted

        assert mariner_conn.is_open

    assert conn_info_queue.empty()

    await eventer_server.async_close()

    eventer_disconn_infos = set()
    while not conn_info_queue.empty():
        disconnected_eventer_conn_info = conn_info_queue.get_nowait()
        eventer_disconn_infos.add(disconnected_eventer_conn_info)

    assert eventer_disconn_infos == eventer_conn_infos

    assert server.is_open
    all(mariner_conn.is_open for mariner_conn in mariner_conns)

    server.close()

    for mariner_conn in mariner_conns:
        await mariner_conn.wait_closed()

    await server.wait_closed()


async def test_status(conf, mariner_addr, eventer_addr):
    clients_count = 10

    clients_conf = [{'name': f'cli{i}',
                     'token': f'cli{i} token',
                     'subscriptions': []}
                    for i in range(clients_count)]
    conf = json.set_(conf, 'clients', clients_conf)

    init_req_msgs = [
        transport.InitReqMsg(
            client_name=client_conf['name'],
            client_token=client_conf['token'],
            subscriptions=client_conf['subscriptions'],
            server_id=None,
            persisted=False) for client_conf in clients_conf]

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        status=hat.event.common.Status.STANDBY)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conns = []
    for init_req_msg in init_req_msgs:
        mariner_conn = await transport.connect(mariner_addr)
        mariner_conns.append(mariner_conn)

        await mariner_conn.send(init_req_msg)
        init_resp = await mariner_conn.receive()
        assert init_resp.success is True

    for new_status in [hat.event.common.Status.OPERATIONAL,
                       hat.event.common.Status.STANDBY,
                       hat.event.common.Status.OPERATIONAL]:
        await eventer_server.set_status(new_status)

        for mariner_conn in mariner_conns:
            status_msg = await mariner_conn.receive()
            assert isinstance(status_msg, transport.StatusMsg)
            assert status_msg.status == new_status

    await server.async_close()
    await eventer_server.async_close()


@pytest.mark.parametrize('evt_types_notified, clients_notified', [
    ([('a', 'b', 'c'), ('b', 'c', 'e'), ('x', 'y')],
     {'cli1': [('a', 'b', 'c'), ('b', 'c', 'e')],
      'cli2': [('a', 'b', 'c')]}),

    ([('x', 'y'), ('y', 'z')],
     {'cli1': [],
      'cli2': []}),

    ([('b', 'c', 'e'), ('a', 'b')],
     {'cli1': [('b', 'c', 'e')],
      'cli2': []}),

    ([('d', 'e', 'f'), ('a', 'b')],
     {'cli1': [],
      'cli2': [('d', 'e', 'f')]})])
@pytest.mark.parametrize('event_payload', [
    None,
    hat.event.common.EventPayloadJson(42),
    hat.event.common.EventPayloadBinary(type='type',
                                        data=b'data')])
@pytest.mark.parametrize('persisted', [True, False])
async def test_events(conf, mariner_addr, eventer_addr, evt_types_notified,
                      event_payload, clients_notified, persisted):
    clients_conf = [
        {'name': 'cli1',
         'token': 'cli1 token',
         'subscriptions': [('a', 'b', 'c'),
                           ('b', 'c', 'e')]},
        {'name': 'cli2',
         'token': 'cli2 token',
         'subscriptions': [('a', 'b', 'c'),
                           ('d', 'e', 'f')]}]
    conf = json.set_(conf, 'clients', clients_conf)

    eventer_server = await hat.event.eventer.listen(eventer_addr)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conns = {}
    for client_conf in clients_conf:
        mariner_conn = await transport.connect(mariner_addr)
        mariner_conns[client_conf['name']] = mariner_conn
        init_req = transport.InitReqMsg(
            client_name=client_conf['name'],
            client_token=client_conf['token'],
            subscriptions=client_conf['subscriptions'],
            server_id=None,
            persisted=persisted)
        await mariner_conn.send(init_req)
        _ = await mariner_conn.receive()

    events = [
        hat.event.common.Event(
            id=hat.event.common.EventId(1, 2, 3),
            type=event_type,
            timestamp=hat.event.common.now(),
            source_timestamp=None,
            payload=event_payload) for event_type in evt_types_notified]

    await eventer_server.notify_events(events, persisted)

    for client_name, client_events_notified in clients_notified.items():
        events_expected = [event for event in events
                           if event.type in client_events_notified]
        mariner_conn = mariner_conns[client_name]

        if events_expected:
            msg_events = await mariner_conn.receive()
            assert isinstance(msg_events, transport.EventsMsg)

            assert msg_events.events == events_expected

        with pytest.raises(asyncio.TimeoutError):
            await aio.wait_for(mariner_conn.receive(), timeout=0.01)

    await server.async_close()
    await eventer_server.async_close()


@pytest.mark.parametrize('query_params', [
    hat.event.common.QueryLatestParams(
            event_types=[('*',)]),
    hat.event.common.QueryLatestParams(
            event_types=[('a', 'b'), ('c', 'd', 'e'), ('1', '2')]),

    hat.event.common.QueryTimeseriesParams(
        event_types=None,
        t_from=None,
        t_to=None,
        source_t_from=None,
        source_t_to=None,
        order=hat.event.common.Order.DESCENDING,
        order_by=hat.event.common.OrderBy.TIMESTAMP,
        max_results=None,
        last_event_id=None),
    hat.event.common.QueryTimeseriesParams(
        event_types=[('quer', 'ied', 'eve'), ('nt', 'typ', 'es')],
        t_from=hat.event.common.Timestamp(s=1, us=123),
        t_to=hat.event.common.Timestamp(s=5, us=123),
        source_t_from=hat.event.common.Timestamp(s=123, us=456),
        source_t_to=hat.event.common.Timestamp(s=321, us=654),
        order=hat.event.common.Order.ASCENDING,
        order_by=hat.event.common.OrderBy.SOURCE_TIMESTAMP,
        max_results=345,
        last_event_id=hat.event.common.EventId(
            server=3,
            session=4,
            instance=5)),

    hat.event.common.QueryServerParams(
        server_id=1,
        persisted=False,
        max_results=None,
        last_event_id=None),
    hat.event.common.QueryServerParams(
        server_id=1,
        persisted=True,
        max_results=123,
        last_event_id=hat.event.common.EventId(
            server=3,
            session=456,
            instance=5678))])
@pytest.mark.parametrize('query_result', [
    hat.event.common.QueryResult(
        events=[],
        more_follows=False),
    hat.event.common.QueryResult(
        events=[
            hat.event.common.Event(
                id=hat.event.common.EventId(1, 2, 3),
                type=('a', 'b', 'c'),
                timestamp=hat.event.common.now(),
                source_timestamp=hat.event.common.now(),
                payload=hat.event.common.EventPayloadJson({'a': {'b': i}}))
            for i in range(3)],
        more_follows=True)
    ])
async def test_query(conf, eventer_addr, mariner_addr,
                     query_params, query_result):
    persisted = False
    server_id = None

    client_conf = {'name': 'cli1',
                   'token': 'client token',
                   'subscriptions': []}
    clients = [client_conf]
    conf = json.set_(conf, 'clients', clients)

    def on_query(conn_info, eventer_query_params):
        assert query_params == eventer_query_params

        assert conn_info.client_name == f"mariner/{conf['name']}/{client_conf['name']}"  # NOQA
        assert conn_info.client_token == conf['eventer']['token']
        assert (list(conn_info.subscription.get_query_types()) ==
                client_conf['subscriptions'])
        assert conn_info.server_id == server_id
        assert conn_info.persisted == persisted

        return query_result

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        query_cb=on_query)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conn = await transport.connect(mariner_addr)
    await mariner_conn.send(transport.InitReqMsg(
        client_name=client_conf['name'],
        client_token=client_conf['token'],
        subscriptions=client_conf['subscriptions'],
        server_id=server_id,
        persisted=persisted))
    _ = await mariner_conn.receive()

    query_req = transport.QueryReqMsg(
        query_id=54321,
        params=query_params)
    await mariner_conn.send(query_req)

    query_resp = await mariner_conn.receive()

    assert query_resp.query_id == query_req.query_id
    assert query_resp.result == query_result

    await server.async_close()
    await eventer_server.async_close()


async def test_ping(conf, mariner_addr, eventer_addr):
    client_conf = {'name': 'cli1',
                   'token': 'client token',
                   'subscriptions': []}
    clients = [client_conf]
    conf = json.set_(conf, 'clients', clients)

    eventer_server = await hat.event.eventer.listen(eventer_addr)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conn = await transport.connect(mariner_addr)
    await mariner_conn.send(transport.InitReqMsg(
        client_name=client_conf['name'],
        client_token=client_conf['token'],
        subscriptions=client_conf['subscriptions'],
        server_id=None,
        persisted=False))
    _ = await mariner_conn.receive()

    for i in range(10):
        ping_req = transport.PingReqMsg(ping_id=654 + i * 2)
        await mariner_conn.send(ping_req)

        ping_res = await mariner_conn.receive()
        assert isinstance(ping_res, transport.PingResMsg)
        assert ping_res.ping_id == ping_req.ping_id

    await server.async_close()
    await eventer_server.async_close()


async def test_register(conf, mariner_addr, eventer_addr):
    client_conf = {'name': 'cli1',
                   'token': 'client token',
                   'subscriptions': []}
    clients = [client_conf]
    conf = json.set_(conf, 'clients', clients)

    eventer_server = await hat.event.eventer.listen(eventer_addr)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conn = await transport.connect(mariner_addr)
    await mariner_conn.send(transport.InitReqMsg(
        client_name=client_conf['name'],
        client_token=client_conf['token'],
        subscriptions=client_conf['subscriptions'],
        server_id=None,
        persisted=False))
    _ = await mariner_conn.receive()

    register_req_msg = transport.RegisterReqMsg(
        register_id=654321,
        register_events=[hat.event.common.RegisterEvent(
            type=('a', 'xyz', 'b'),
            source_timestamp=hat.event.common.now(),
            payload=hat.event.common.EventPayloadJson('abc'))])
    await mariner_conn.send(register_req_msg)

    register_resp_msg = await mariner_conn.receive()
    assert isinstance(register_resp_msg, transport.RegisterResMsg)
    assert register_resp_msg.register_id == register_req_msg.register_id
    assert register_resp_msg.success is False
    assert register_resp_msg.events is None

    await server.async_close()
    await eventer_server.async_close()


async def test_eventer_closes_on_mariner_close(conf, mariner_addr,
                                               eventer_addr):
    clients_count = 10
    conn_info_queue = aio.Queue()

    def on_connection(conn_info):
        conn_info_queue.put_nowait(conn_info)

    init_msgs = [
        transport.InitReqMsg(
            client_name=f"cli{i}",
            client_token=f"cli{i} token",
            subscriptions=[(f'x{i}', f'y{i}'),
                           ('a', 'b', 'c')],
            server_id=i,
            persisted=bool(i % 2))
        for i in range(clients_count)]

    clients_conf = [{'name': i.client_name,
                     'token': i.client_token,
                     'subscriptions': [i.subscriptions[0],
                                       ('d', 'e', 'f')]}
                    for i in init_msgs]
    conf = json.set_(conf, 'clients', clients_conf)

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        connected_cb=on_connection,
        disconnected_cb=on_connection)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conns = set()
    eventer_conn_infos = set()
    for init_req in init_msgs:
        mariner_conn = await transport.connect(mariner_addr)

        await mariner_conn.send(init_req)
        init_resp = await mariner_conn.receive()
        assert init_resp.success is True
        conn_info = await conn_info_queue.get()
        mariner_conns.add(mariner_conn)
        eventer_conn_infos.add(conn_info)

    while mariner_conns:
        mariner_conn = mariner_conns.pop()
        mariner_conn.close()

        disconn_info = await conn_info_queue.get()
        assert disconn_info in eventer_conn_infos

        assert all(conn.is_open for conn in mariner_conns)

    await server.async_close()
    await eventer_server.async_close()


@pytest.mark.parametrize('invalid_msg', [
    transport.QueryReqMsg(
        query_id=123,
        params=hat.event.common.QueryLatestParams(
            event_types=[('*',)]),),
    transport.PingReqMsg(ping_id=456),
    transport.RegisterReqMsg(
        register_id=345,
        register_events=[hat.event.common.RegisterEvent(
            type=('a', 'xyz', 'b'),
            source_timestamp=hat.event.common.now(),
            payload=hat.event.common.EventPayloadJson('abc'))])
    ])
async def test_invalid_init_msg(conf, mariner_addr, eventer_addr, invalid_msg):
    conn_info_queue = aio.Queue()

    def on_connection(conn_info):
        conn_info_queue.put_nowait(conn_info)

    clients = [{'name': 'cli1',
                'token': 'cli1 token',
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        connected_cb=on_connection)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conn = await transport.connect(mariner_addr)

    await mariner_conn.send(invalid_msg)

    with pytest.raises(ConnectionError):
        await mariner_conn.receive()
    await mariner_conn.wait_closed()

    assert conn_info_queue.empty()

    await server.async_close()
    await eventer_server.async_close()


@pytest.mark.parametrize('invalid_msg', [
    transport.InitReqMsg(
        client_name='cli1',
        client_token='cli1 token',
        subscriptions=[],
        server_id=None,
        persisted=False),
    transport.InitResMsg(
        success=True,
        status=hat.event.common.Status.STANDBY,
        error=None),
    transport.StatusMsg(
        status=hat.event.common.Status.OPERATIONAL),
    transport.EventsMsg(events=[]),
    transport.QueryResMsg(query_id=123,
                          result=hat.event.common.QueryResult(
                              events=[],
                              more_follows=False)),
    transport.PingResMsg(ping_id=456)
    ])
async def test_invalid_message(conf, mariner_addr, eventer_addr, invalid_msg):
    conn_info_queue = aio.Queue()

    def on_connection(conn_info):
        conn_info_queue.put_nowait(conn_info)

    client_name = 'cli1'
    client_token = 'cli1 token'
    subscriptions = []
    server_id = None
    persisted = False

    clients = [{'name': client_name,
                'token': client_token,
                'subscriptions': []}]
    conf = json.set_(conf, 'clients', clients)

    eventer_server = await hat.event.eventer.listen(
        eventer_addr,
        connected_cb=on_connection,
        disconnected_cb=on_connection)

    server = await hat.mariner.server.server.create_server(conf)

    mariner_conn = await transport.connect(mariner_addr)

    init_req = transport.InitReqMsg(
        client_name=client_name,
        client_token=client_token,
        subscriptions=subscriptions,
        server_id=server_id,
        persisted=persisted)
    await mariner_conn.send(init_req)
    init_resp = await mariner_conn.receive()
    assert init_resp.success is True
    conn_info = await conn_info_queue.get()

    await mariner_conn.send(invalid_msg)

    with pytest.raises(ConnectionError):
        await mariner_conn.receive()
    await mariner_conn.wait_closed()

    disconn_info = await conn_info_queue.get()
    assert disconn_info == conn_info

    await server.async_close()
    await eventer_server.async_close()
