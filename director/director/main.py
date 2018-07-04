from asyncio import sleep
from collections import defaultdict, deque
from itertools import count
from prodict import Prodict
from time import time
import asyncio
import ujson
import copy

from band import settings, dome, rpc, logger, app, run_task
from band.constants import NOTIFY_ALIVE, REQUEST_STATUS, OK, FRONTIER_SERVICE, DIRECTOR_SERVICE

from .constants import STATUS_RUNNING
from .helpers import merge
from .state_ctx import StateCtx
from . import dock, state, band_config


@dome.expose(name='list')
async def lst(**params):
    """
    Containers list with status information
    """
    # By default return all containers
    cs = await dock.containers(status=params.pop('status', None))
    res = {}
    for name in state.state:
        res[name] = state.get_appstatus(name)
    for name, cont in cs.items():
        res[name].update(cont.short_info) if name in res else res.update(
            dict(name=cont.short_info))
    return list(res.values())



@dome.expose()
async def registrations(**params):
    """
    Provide global RPC registrations information
    """
    conts = await lst(status=STATUS_RUNNING)
    methods = []
    # Iterating over containers and their methods
    for container in conts:
        if 'register' in container:
            for method_reg in container.register:
                logger.info(method_reg)
                methods.append({'service': container.name, **method_reg})
    return dict(register=methods)


@dome.expose()
async def regs2(**params):
    """
    """
    
    # regs = [{'service': k, **reg} for k, reg in state.registraions().items()]
    regs = state.registraions()
    # # Iterating over containers and their methods
    # for container in conts:
    #     if 'register' in container:
    #         for method_reg in container.register:
    #             logger.info(method_reg)
    #             methods.append({'service': container.name, **method_reg})
    return dict(register=regs)


@dome.expose(name=NOTIFY_ALIVE)
async def sync_status(name, **params):
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


async def check_regs_changed():
    key = hash(ujson.dumps(await registrations()))
    logger.info("key: %s", key)
    if key != state.last_key:
        state.last_key = key
        await sync_status(name=FRONTIER_SERVICE)


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
    band_config.save_config(name, params)
    return await dock.run_container(name, **params)


@dome.expose(path='/restart/{name}')
async def restart(name, **params):
    """
    Restart service
    """
    async with StateCtx(name, check_regs_changed()):
        return await dock.restart_container(name)

    # state.clear_status(name)


@dome.expose(path='/stop/{name}')
async def stop(name, **params):
    """
    stop container
    """
    async with StateCtx(name, check_regs_changed()):
        return await dock.stop_container(name)


@dome.expose(path='/rm/{name}')
async def remove(name, **params):
    """
    Unload/remove service
    """
    async with StateCtx(name, check_regs_changed()):
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
            # await dock.init()
            for c in await dock.containers(struct=list):
                if c.name != DIRECTOR_SERVICE and c.running:
                    await sync_status(c.name)
                    started.add(c.name)
            for name in startup - started:
                if name: await dock.run_container(name)
        # Remove expired services
        await check_regs_changed()
        await sleep(5)


@dome.shutdown
async def unloader():
    """
    Graceful shutdown task
    """
    await dock.close()
    # pass
