from asyncio import sleep
from collections import defaultdict, deque
from itertools import count
from prodict import Prodict
from time import time
import asyncio

from band import settings, dome, rpc, logger, app, run_task
from band.constants import NOTIFY_ALIVE, REQUEST_STATUS, OK, FRONTIER_SERVICE, DIRECTOR_SERVICE

from .constants import STATUS_RUNNING
from .state_ctx import StateCtx
from . import dock, state


@dome.expose(name='list')
async def lst(**params):
    """
    Containers list with status information
    """
    # By default return all containers
    status = params.pop('status', None)
    cs = await dock.containers(status=status)
    res = []
    for n in state.state:
        # dock_data = n in cs and cs[n].short_info or {}
        res.append(state.get_appstatus(n))
    return res
    # return [
    #     Prodict(**state.get_appstatus(n), **()) for
    # ]


@dome.expose()
async def registrations(**params):
    """
    Provide global RPC registrations information
    """
    params = Prodict()
    conts = await lst(status=STATUS_RUNNING)
    methods = []
    # Iterating over containers and their methods
    for c in conts:
        if 'register' in c:
            for cm in c.register:
                logger.info(cm)
                methods.append({'service': c.name, **cm})
    return dict(register=methods)


@dome.expose(name=NOTIFY_ALIVE)
async def sync_status(name=FRONTIER_SERVICE, **params):
    """
    Listen for services promotions then ask their statuses.
    It some cases takes payload to reduce calls amount
    """
    payload = Prodict()
    if name == FRONTIER_SERVICE:
        payload.update(await registrations())
    status = await rpc.request(name, REQUEST_STATUS, **payload)
    if status:
        state.set_status(name, status)
    # Pushing update to frontier
    if name != FRONTIER_SERVICE:
        await sync_status(FRONTIER_SERVICE)


@dome.expose(path='/show/{name}')
async def show(name, **params):
    """
    Returns container details
    """
    container = await dock.get(name)
    return container and container.short_info


@dome.expose()
async def images(**params):
    """
    Available images list
    """
    return await dock.imgnav.lst()


@dome.expose(path='/status/{name}')
async def status_call(name, **params):
    """
    Ask service status
    """
    return await rpc.request(name, REQUEST_STATUS)


@dome.expose(path='/call/{name}/{method}')
async def call(name, method, **params):
    """
    Call service method
    """
    return await rpc.request(name, method, **params)


@dome.expose(path='/run/{name}')
async def run(name, **params):
    """
    Create image and run new container with service
    """
    logger.info('Run request with params: %s', params)
    return await dock.run_container(name, **params)


@dome.expose(path='/restart/{name}')
async def restart(name, **params):
    """
    Restart service
    """
    async with StateCtx(name, sync_status()):
        return await dock.restart_container(name)

    # state.clear_status(name)


@dome.expose(path='/stop/{name}')
async def stop(name, **params):
    """
    stop container
    """
    async with StateCtx(name, sync_status()):
        return await dock.stop_container(name)


@dome.expose(path='/rm/{name}')
async def remove(name, **params):
    """
    Unload/remove service
    """
    async with StateCtx(name, sync_status()):
        return await dock.remove_container(name)


@dome.tasks.add
async def startup():
    """
    Startup and heart-beat task
    """
    startup = set(settings.startup)
    started = set([DIRECTOR_SERVICE])

    for num in count():
        if num == 0:
            # checking current action
            for c in await dock.init():
                if c.name != DIRECTOR_SERVICE and c.running:
                    await sync_status(c.name)
                    started.add(c.name)
            for name in startup - started:
                if name: await dock.run_container(name)
        # Remove expired services
        state.check_expire()
        await sleep(5)


@dome.shutdown
async def unloader():
    """
    Graceful shutdown task
    """
    await dock.close()
    # pass
