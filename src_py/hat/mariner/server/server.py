import logging

from hat import aio
from hat import json
from hat.drivers import tcp
import hat.event.common
import hat.event.eventer

from hat.mariner import transport


mlog: logging.Logger = logging.getLogger(__name__)


async def create_server(conf: json.Data) -> 'Server':
    srv = Server()
    srv._name = conf['name']
    srv._eventer_conf = conf['eventer']
    srv._client_confs = {client_conf['name']: client_conf
                         for client_conf in conf['clients']}

    srv._srv = await transport.listen(
        connection_cb=srv._on_connection,
        addr=tcp.Address(host=conf['mariner']['host'],
                         port=conf['mariner']['port']),
        bind_connections=True)

    return srv


class Server(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._srv.async_group

    async def _on_connection(self, mariner_conn):
        try:
            client = await _create_client(component_name=self._name,
                                          eventer_conf=self._eventer_conf,
                                          client_confs=self._client_confs,
                                          mariner_conn=mariner_conn)

        except Exception as e:
            mlog.error("error initializing client: %s", e, exc_info=e)

            await aio.uncancellable(mariner_conn.async_close())
            return

        try:
            await client.wait_closing()

        finally:
            await aio.uncancellable(client.async_close())


async def _create_client(component_name, eventer_conf, client_confs,
                         mariner_conn):
    init_req = await mariner_conn.receive()
    if not isinstance(init_req, transport.InitReqMsg):
        raise Exception('invalid init request')

    send_queue = aio.Queue(1024)

    async def on_status(eventer_client, status):
        msg = transport.StatusMsg(status=status)
        await send_queue.put(msg)

    async def on_events(eventer_client, events):
        msg = transport.EventsMsg(events=events)
        await send_queue.put(msg)

    client_conf = client_confs.get(init_req.client_name)

    try:
        if not client_conf:
            raise Exception('invalid client name')

        if client_conf['token'] != init_req.client_token:
            raise Exception('invalid client token')

        conf_subscription = hat.event.common.create_subscription(
            client_conf['subscriptions'])
        mariner_subscription = hat.event.common.create_subscription(
            init_req.subscriptions)

        subscription = conf_subscription.intersection(mariner_subscription)

    except Exception as e:
        init_res = transport.InitResMsg(success=False,
                                        status=None,
                                        error=str(e))
        await mariner_conn.send(init_res)
        raise

    try:
        eventer_client = await hat.event.eventer.connect(
            addr=tcp.Address(host=eventer_conf['host'],
                             port=eventer_conf['port']),
            client_name=f'mariner/{component_name}/{init_req.client_name}',
            client_token=eventer_conf['token'],
            subscriptions=subscription.get_query_types(),
            server_id=init_req.server_id,
            persisted=init_req.persisted,
            status_cb=on_status,
            events_cb=on_events)

        try:
            eventer_client.async_group.spawn(aio.call_on_cancel,
                                             mariner_conn.close)
            mariner_conn.async_group.spawn(aio.call_on_cancel,
                                           eventer_client.async_close)

        except Exception:
            await aio.uncancellable(eventer_client.async_close())
            raise

    except Exception:
        init_res = transport.InitResMsg(
            success=False,
            status=None,
            error='error connecting to eventer server')
        await mariner_conn.send(init_res)
        raise

    init_res = transport.InitResMsg(success=True,
                                    status=eventer_client.status,
                                    error=None)
    await mariner_conn.send(init_res)

    client = _Client()
    client._conf = client_conf
    client._send_queue = send_queue
    client._query_queue = aio.Queue(1024)
    client._mariner_conn = mariner_conn
    client._eventer_client = eventer_client

    client.async_group.spawn(client._receive_loop)
    client.async_group.spawn(client._send_loop)
    client.async_group.spawn(client._query_loop)

    return client


class _Client(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._mariner_conn.async_group

    async def _receive_loop(self):
        try:
            while True:
                req = await self._mariner_conn.receive()

                if isinstance(req, transport.RegisterReqMsg):
                    res = transport.RegisterResMsg(register_id=req.register_id,
                                                   success=False,
                                                   events=None)
                    await self._send_queue.put(res)

                elif isinstance(req, transport.QueryReqMsg):
                    await self._query_queue.put(req)

                elif isinstance(req, transport.PingReqMsg):
                    res = transport.PingResMsg(ping_id=req.ping_id)
                    await self._send_queue.put(res)

                else:
                    raise Exception('invalid message type')

        except ConnectionError:
            pass

        except Exception as e:
            mlog.error('receive loop error: %s', e, exc_info=e)

        finally:
            self.close()

    async def _send_loop(self):
        try:
            while True:
                msg = await self._send_queue.get()

                await self._mariner_conn.send(msg)

        except ConnectionError:
            pass

        except Exception as e:
            mlog.error('send loop error: %s', e, exc_info=e)

        finally:
            self.close()

    async def _query_loop(self):
        try:
            while True:
                req = await self._query_queue.get()

                result = await self._eventer_client.query(req.params)

                res = transport.QueryResMsg(query_id=req.query_id,
                                            result=result)
                await self._send_queue.put(res)

        except ConnectionError:
            pass

        except Exception as e:
            mlog.error('query loop error: %s', e, exc_info=e)

        finally:
            self.close()
